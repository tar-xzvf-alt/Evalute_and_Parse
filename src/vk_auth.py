"""Browser-assisted legacy VK login; no GUI imports and no password handling."""

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from vk_collection import CollectionError


def authorization_url():
    """Keep the existing GUI application's OAuth flow, not an invented refresh flow."""
    return "https://oauth.vk.com/authorize?" + urlencode({
        "client_id": "54447901", "display": "page",
        "redirect_uri": "https://oauth.vk.com/blank.html",
        "response_type": "token", "v": "5.131",
    })


def parse_redirect(value, now=None):
    """Return secret and non-secret lifetime; never include supplied URL in errors."""
    try:
        url = urlsplit(value.strip())
        if (url.scheme != "https" or url.netloc not in {"oauth.vk.com", "oauth.vk.ru"}
                or url.path != "/blank.html" or url.query):
            raise ValueError
        fields = parse_qs(url.fragment, keep_blank_values=True)
        if "error" in fields:
            raise CollectionError("VK отклонил авторизацию. Проверьте результат в браузере.")
        tokens = fields.get("access_token", [])
        if len(tokens) != 1 or not tokens[0] or any(c.isspace() or ord(c) < 32 for c in tokens[0]):
            raise ValueError
        lifetime = fields.get("expires_in")
        if lifetime is not None and (len(lifetime) != 1 or not lifetime[0].isascii()
                                     or not lifetime[0].isdigit()):
            raise ValueError
        seconds = int(lifetime[0]) if lifetime else None
        received = now or datetime.now(timezone.utc)
        expires = received + timedelta(seconds=seconds) if seconds else None
        return tokens[0], {"received_utc": received.isoformat(), "expires_in": seconds,
                           "expires_at_utc": expires.isoformat() if expires else None,
                           "expiry_basis": "reported_lifetime_from_local_receipt_not_verified"}
    except (ValueError, TypeError, OverflowError):
        raise CollectionError("Ожидается полный итоговый URL https://oauth.vk.com/blank.html#access_token=… или https://oauth.vk.ru/blank.html#access_token=… без изменений. Параметры expires_in и user_id удалять не нужно.") from None


def save_login(destination, token, metadata):
    """Stage private files before replacement; retain the old secret on staging errors."""
    destination = Path(destination).absolute()
    sidecar = destination.with_name(destination.name + ".meta.json")
    if (not destination.parent.is_dir() or destination.is_symlink() or sidecar.is_symlink()
            or destination.is_dir() or sidecar.is_dir()):
        raise CollectionError("Нужен обычный файл токена в существующем каталоге, не символическая ссылка.")
    staged = []
    token_saved = False
    try:
        for target, text in ((destination, token + "\n"),
                             (sidecar, json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")):
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent,
                                             prefix=".parsevk-auth-", delete=False) as stream:
                temporary = Path(stream.name)
                staged.append((temporary, target))
                os.chmod(temporary, 0o600)
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
        os.replace(*staged[0])
        token_saved = True
        os.replace(*staged[1])
    except OSError:
        if token_saved:
            # Old sidecar must not be mistaken for this new token's lifetime.
            try:
                sidecar.unlink(missing_ok=True)
            except OSError:
                pass
            raise CollectionError("Токен сохранён, но срок действия сохранить не удалось; старым метаданным не доверяйте.") from None
        raise CollectionError("Не удалось сохранить токен; прежний файл не заменён.") from None
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
    return destination, sidecar
