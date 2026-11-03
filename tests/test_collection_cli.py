import contextlib
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from collection_cli import main
from collection_workflow import assess_groups, normalize_settings
from vk_collection import CollectionError, load_profile, save_profile
from cli_fixture import FixtureClient


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.env = dict(os.environ, VK_TOKEN="FIXTURE_SECRET", DISPLAY="")
        self.profile = self.directory / "profile.json"
        save_profile(self.profile, {"year": "2019", "minimum": 1, "maximum": 1,
                                   "folder": str(self.directory), "min_words": 0,
                                   "mode": "Автоматически"},
                     [{"id": 1, "name": "Новости", "selected": False},
                      {"id": 2, "name": "Другой", "selected": True}])

    def invoke(self, *args, fixture=True):
        entry = ROOT / "tests" / "cli_fixture.py" if fixture else ROOT / "parsevk.py"
        return subprocess.run([sys.executable, str(entry), *map(str, args)],
                              cwd=self.directory, env=self.env, text=True,
                              capture_output=True, timeout=15)

    def test_real_entrypoint_help_without_display(self):
        result = self.invoke("--help", fixture=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("collect", result.stdout)

    def test_invalid_arguments_are_nonzero_without_network(self):
        result = self.invoke("search", fixture=False)
        self.assertEqual(result.returncode, 2)

    def test_search_json_and_profile_are_gui_compatible(self):
        profile = self.directory / "search-profile.json"
        result = self.invoke("search", "--query", "новости", "--limit", "1", "--save-profile", profile)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(len(data["groups"]), 1)
        self.assertFalse(data["groups"][0]["selected"])
        self.assertNotIn("year", data["settings"])
        self.assertEqual(load_profile(profile)["groups"][0]["id"], 1)
        self.assertNotIn("FIXTURE_SECRET", result.stdout + result.stderr + profile.read_text())

    def test_assess_verify_and_select_use_shared_policy(self):
        for command in ("assess", "verify", "select"):
            result = self.invoke(command, "--input", self.profile)
            self.assertEqual(result.returncode, 0, result.stderr)
            actual = json.loads(result.stdout)
            rows = load_profile(self.profile)["groups"]
            import threading
            client = FixtureClient("secret", threading.Event())
            expected = assess_groups(client, load_profile(self.profile)["settings"], rows,
                                     exact=command == "verify", automatic=command == "select")
            self.assertEqual(actual["groups"], expected)
        self.assertTrue(actual["groups"][0]["selected"])
        self.assertFalse(actual["groups"][1]["selected"])

    def test_partial_source_errors_write_json_and_return_four(self):
        save_profile(self.profile, {"year": "2019"},
                     [{"id": 1, "name": "OK"}, {"id": 99, "name": "Denied"}])
        result = self.invoke("verify", "--input", self.profile)
        self.assertEqual(result.returncode, 4, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["status"], "partial")
        self.assertIsNone(data["groups"][1]["count"])
        self.assertIn("Проверка", result.stderr)

    def test_run_keeps_selected_set_even_in_automatic_mode(self):
        result = self.invoke("run", "--profile", self.profile)
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        manifest = json.loads(Path(summary["manifest"]).read_text())
        self.assertEqual([g["id"] for g in manifest["groups"]], [2])
        self.assertEqual(manifest["groups"][0]["retained"], 1)

    def test_collect_explicit_ids_and_year_override(self):
        result = self.invoke("collect", "--groups", "1", "--year", "2020",
                             "--min-words", "0", "--output", self.directory)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(Path(json.loads(result.stdout)["manifest"]).read_text())
        self.assertEqual(data["year"], 2020)
        self.assertEqual(data["groups"][0]["retained"], 0)

    def test_token_file_overrides_environment_and_errors_are_redacted(self):
        token = self.directory / "token.txt"
        token.write_text("OTHER_SECRET")
        result = self.invoke("search", "--query", "fail", "--token-file", token)
        self.assertEqual(result.returncode, 3)
        self.assertNotIn("OTHER_SECRET", result.stderr)
        self.assertNotIn("FIXTURE_SECRET", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_missing_token_and_bad_profile_return_two(self):
        with patch.dict(os.environ, {"VK_TOKEN": ""}), patch("collection_cli.Path.is_file", return_value=False):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["search", "--query", "новости"], client_factory=FixtureClient), 2)
        self.profile.write_text('{"version":1,"settings":{},"groups":[{}]}')
        result = self.invoke("verify", "--input", self.profile)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)

    def test_cancel_and_interrupt_return_130(self):
        for query in ("cancel", "interrupt"):
            result = self.invoke("search", "--query", query)
            self.assertEqual(result.returncode, 130)
            self.assertEqual(result.stdout, "")

    def test_output_file_is_json_and_quiet_suppresses_progress(self):
        output = self.directory / "result.json"
        result = self.invoke("verify", "--input", self.profile, "--output", output, "--quiet")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")
        self.assertEqual(json.loads(output.read_text())["status"], "complete")

    def test_empty_selection_does_not_silently_search(self):
        save_profile(self.profile, {"year": "2019", "folder": str(self.directory), "mode": "Автоматически"},
                     [{"id": 1, "name": "Новости", "selected": False}])
        result = self.invoke("run", "--profile", self.profile)
        self.assertEqual(result.returncode, 2)

    def test_numeric_settings_reject_invalid_values(self):
        for settings in ({"minimum": -1}, {"candidates": 1001}, {"maximum": True},
                         {"min_words": 1.5}, {"year": 2019.5}, {"year": True}):
            with self.assertRaises(CollectionError):
                normalize_settings(settings)

    def test_output_cannot_overwrite_token(self):
        token = self.directory / "token.txt"
        token.write_text("PRESERVE_ME")
        result = self.invoke("search", "--query", "новости", "--token-file", token, "--output", token)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(token.read_text(), "PRESERVE_ME")

    def test_output_and_saved_profile_cannot_collide(self):
        path = self.directory / "result.json"
        result = self.invoke("search", "--query", "новости", "--output", path, "--save-profile", path)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(path.exists())

    def test_collection_failure_preserves_completed_files_and_manifest(self):
        for last_id, expected_code, status in ((99, 3, "failed"), (98, 130, "cancelled")):
            output = self.directory / str(last_id)
            output.mkdir()
            result = self.invoke("collect", "--groups", f"1,{last_id}", "--year", "2019",
                                 "--min-words", "0", "--output", output)
            self.assertEqual(result.returncode, expected_code, result.stderr)
            manifest_path = next(output.glob("collection_*.json"))
            manifest = json.loads(manifest_path.read_text())
            self.assertEqual(manifest["status"], status)
            self.assertEqual(manifest["groups"][0]["status"], "complete")
            self.assertTrue((output / manifest["groups"][0]["file"]).is_file())
            self.assertEqual(manifest["groups"][1]["status"], status)

    def test_cli_resume_keeps_first_file_and_completes_second(self):
        result = self.invoke('collect', '--groups', '1,99', '--year', '2019',
                             '--min-words', '0', '--output', self.directory)
        self.assertEqual(result.returncode, 3, result.stderr)
        old_path = next(self.directory.glob('collection_*.json'))
        old = json.loads(old_path.read_text())
        first_path = self.directory / old['groups'][0]['file']
        first_bytes = first_path.read_bytes()
        self.env['FIXTURE_ALLOW_99'] = '1'
        result = self.invoke('collect', '--groups', '1,99', '--year', '2019',
                             '--min-words', '0', '--output', self.directory,
                             '--resume', old_path)
        self.assertEqual(result.returncode, 0, result.stderr)
        current = json.loads(Path(json.loads(result.stdout)['manifest']).read_text())
        self.assertEqual(current['status'], 'complete')
        self.assertTrue(current['groups'][0]['reused'])
        self.assertEqual(first_path.read_bytes(), first_bytes)
        self.assertEqual(current['groups'][0]['file'], old['groups'][0]['file'])
        self.assertEqual(current['groups'][1]['status'], 'complete')

    def test_resume_includes_source_not_attempted_after_first_failure(self):
        result = self.invoke('collect', '--groups', '99,1', '--year', '2019',
                             '--min-words', '0', '--output', self.directory)
        self.assertEqual(result.returncode, 3, result.stderr)
        old_path = next(self.directory.glob('collection_*.json'))
        old = json.loads(old_path.read_text())
        self.assertEqual(old['planned_group_ids'], [99, 1])
        self.assertEqual([g['id'] for g in old['groups']], [99])
        self.env['FIXTURE_ALLOW_99'] = '1'
        result = self.invoke('collect', '--groups', '99,1', '--year', '2019',
                             '--min-words', '0', '--output', self.directory,
                             '--resume', old_path)
        self.assertEqual(result.returncode, 0, result.stderr)
        current = json.loads(Path(json.loads(result.stdout)['manifest']).read_text())
        self.assertEqual([g['id'] for g in current['groups']], [99, 1])

    @unittest.skipIf(sys.platform == "win32", "POSIX signal delivery")
    def test_real_process_signals_return_expected_codes(self):
        for sig in (signal.SIGINT, signal.SIGTERM):
            process = subprocess.Popen([sys.executable, str(ROOT / "tests" / "cli_fixture.py"),
                                        "search", "--query", "wait"], cwd=self.directory,
                                       env=self.env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                self.assertEqual(process.stderr.readline().strip(), "READY")
                process.send_signal(sig)
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 128 + sig, stderr)
                self.assertEqual(stdout, "")
                self.assertNotIn("Traceback", stderr)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()

    def test_search_result_requires_explicit_assessment_year(self):
        path = self.directory / "candidates.json"
        result = self.invoke("search", "--query", "новости", "--output", path)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.invoke("assess", "--input", path)
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
