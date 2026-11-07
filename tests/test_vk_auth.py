import contextlib
import getpass
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from collection_cli import main
from vk_auth import authorization_url, parse_redirect, save_login
from vk_collection import CollectionError


SECRET = "SYNTHETIC_AUTH_FIXTURE"
REDIRECT = "https://oauth.vk.com/blank.html#access_token=" + SECRET + "&expires_in=3600&user_id=123"


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.destination = Path(self.temp.name) / "vk_token.txt"

    def invoke(self, value=REDIRECT, browser=True, terminal=True, effect=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("collection_cli.sys.stdin.isatty", return_value=terminal), \
                patch("collection_cli.getpass.getpass", return_value=value, side_effect=effect) as hidden, \
                patch("collection_cli.webbrowser.open", return_value=True) as opener, \
                patch("collection_cli.VKClient") as client, \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            args = ["auth", "login", "--token-file", str(self.destination)]
            if not browser:
                args.append("--no-browser")
            code = main(args)
        client.assert_not_called()
        self.assertNotIn(SECRET, stdout.getvalue() + stderr.getvalue())
        return code, stdout.getvalue(), stderr.getvalue(), hidden, opener

    def test_url_matches_existing_gui_flow(self):
        url = urlsplit(authorization_url())
        self.assertEqual((url.scheme, url.netloc, url.path), ("https", "oauth.vk.com", "/authorize"))
        fields = parse_qs(url.query)
        self.assertEqual(fields["client_id"], ["54447901"])
        self.assertEqual(fields["response_type"], ["token"])
        self.assertEqual(fields["redirect_uri"], ["https://oauth.vk.com/blank.html"])

    def test_parse_expiry_and_ignore_user_id(self):
        token, metadata = parse_redirect(REDIRECT, datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(token, SECRET)
        self.assertEqual(metadata["expires_at_utc"], "2026-01-01T01:00:00+00:00")
        self.assertNotIn("user_id", metadata)
        self.assertNotIn(SECRET, json.dumps(metadata))

    def test_unknown_and_zero_lifetime_not_claimed_permanent(self):
        for suffix in ("", "&expires_in=0"):
            _, metadata = parse_redirect("https://oauth.vk.com/blank.html#access_token=" + SECRET + suffix)
            self.assertIsNone(metadata["expires_at_utc"])

    def test_vk_ru_redirect_with_lifetime_and_user_id(self):
        value = REDIRECT.replace("oauth.vk.com", "oauth.vk.ru").replace("expires_in=3600", "expires_in=86400")
        token, metadata = parse_redirect(value, datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(token, SECRET)
        self.assertEqual(metadata["expires_in"], 86400)
        self.assertEqual(metadata["expires_at_utc"], "2026-01-02T00:00:00+00:00")
        code, out, _, _, _ = self.invoke(value=value, browser=False)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["status"], "saved")
        self.assertEqual(self.destination.read_text().strip(), SECRET)

    def test_reject_malformed_redirect_without_echo(self):
        for value in (
                SECRET, "http://oauth.vk.com/blank.html#access_token=" + SECRET,
                "https://evil.test/blank.html#access_token=" + SECRET,
                "https://oauth.vk.com.evil.test/blank.html#access_token=" + SECRET,
                "https://oauth.vk.ru.evil.test/blank.html#access_token=" + SECRET,
                "https://user@oauth.vk.ru/blank.html#access_token=" + SECRET,
                "https://user@oauth.vk.com/blank.html#access_token=" + SECRET,
                "https://oauth.vk.com/blank.html?access_token=" + SECRET,
                "https://oauth.vk.com/blank.html#access_token=",
                REDIRECT + "&access_token=SECOND", REDIRECT + "&expires_in=2",
                "https://oauth.vk.com/blank.html#access_token=" + SECRET + "%0A",
                "https://oauth.vk.com/blank.html#access_token=" + SECRET + "&expires_in=-1",
                "https://oauth.vk.com/blank.html#access_token=" + SECRET + "&expires_in=" + "9" * 100,
        ):
            with self.subTest(value=value):
                with self.assertRaises(CollectionError) as error:
                    parse_redirect(value)
                self.assertNotIn(SECRET, str(error.exception))

    def test_oauth_error_description_is_not_echoed(self):
        with self.assertRaises(CollectionError) as error:
            parse_redirect("https://oauth.vk.com/blank.html#error=access_denied&error_description=" + SECRET)
        self.assertNotIn(SECRET, str(error.exception))

    def test_private_atomic_token_and_nonsecret_metadata(self):
        self.destination.write_text("OLD_FIXTURE")
        token, metadata = parse_redirect(REDIRECT)
        dest, meta = save_login(self.destination, token, metadata)
        self.assertEqual(dest.read_text(), SECRET + "\n")
        self.assertEqual(json.loads(meta.read_text()), metadata)
        self.assertNotIn(SECRET, meta.read_text())
        if os.name == "posix":
            self.assertEqual(dest.stat().st_mode & 0o777, 0o600)
            self.assertEqual(meta.stat().st_mode & 0o777, 0o600)
        self.assertFalse(list(self.destination.parent.glob(".parsevk-auth-*")))

    def test_refuse_symlink_and_missing_parent(self):
        target = self.destination.parent / "original"
        target.write_text("OLD_FIXTURE")
        try:
            self.destination.symlink_to(target)
        except OSError:
            self.skipTest("Symlinks unavailable")
        with self.assertRaises(CollectionError):
            save_login(self.destination, SECRET, {})
        self.assertEqual(target.read_text(), "OLD_FIXTURE")
        with self.assertRaises(CollectionError):
            save_login(self.destination.parent / "missing" / "token", SECRET, {})

    def test_staging_failure_keeps_old_token(self):
        self.destination.write_text("OLD_FIXTURE")
        with patch("vk_auth.os.fsync", side_effect=OSError("do not echo " + SECRET)):
            with self.assertRaises(CollectionError) as error:
                save_login(self.destination, SECRET, {})
        self.assertNotIn(SECRET, str(error.exception))
        self.assertEqual(self.destination.read_text(), "OLD_FIXTURE")
        self.assertFalse(list(self.destination.parent.glob(".parsevk-auth-*")))

    def test_metadata_failure_is_reported_as_saved_token_not_total_rollback(self):
        sidecar = self.destination.with_name("vk_token.txt.meta.json")
        sidecar.write_text('{"expires_in": 999}')
        real_replace = os.replace
        def replace(source, target):
            if Path(target) == sidecar:
                raise OSError("fixture failure")
            real_replace(source, target)
        with patch("vk_auth.os.replace", side_effect=replace):
            with self.assertRaisesRegex(CollectionError, "Токен сохранён"):
                save_login(self.destination, SECRET, {})
        self.assertEqual(self.destination.read_text(), SECRET + "\n")
        self.assertFalse(sidecar.exists())

    def test_login_hides_input_and_emits_only_metadata(self):
        code, out, _, hidden, opener = self.invoke()
        self.assertEqual(code, 0)
        hidden.assert_called_once()
        opener.assert_called_once_with(authorization_url())
        result = json.loads(out)
        self.assertEqual(result["status"], "saved")
        self.assertFalse(result["api_validated"])
        self.assertEqual(self.destination.read_text().strip(), SECRET)

    def test_no_browser(self):
        code, _, err, _, opener = self.invoke(browser=False)
        self.assertEqual(code, 0)
        opener.assert_not_called()
        self.assertIn(authorization_url(), err)

    def test_noninteractive_rejected_before_browser_or_input(self):
        code, out, _, hidden, opener = self.invoke(terminal=False)
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        hidden.assert_not_called()
        opener.assert_not_called()
        self.assertFalse(self.destination.exists())

    def test_invalid_url_preserves_old_file(self):
        self.destination.write_text("OLD_FIXTURE")
        code, _, _, _, _ = self.invoke(value="https://invalid.test/#access_token=" + SECRET)
        self.assertEqual(code, 2)
        self.assertEqual(self.destination.read_text(), "OLD_FIXTURE")

    def test_interrupt_eof_and_hidden_input_failure(self):
        for effect, expected in ((KeyboardInterrupt, 130), (EOFError, 130), (getpass.GetPassWarning, 2)):
            with self.subTest(effect=effect):
                code, _, _, _, _ = self.invoke(effect=effect)
                self.assertEqual(code, expected)
                self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()
