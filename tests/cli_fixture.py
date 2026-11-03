"""Deterministic client injected by subprocess tests; never a production flag."""

import sys
import threading
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from vk_collection import Cancelled, CollectionError, year_period


class FixtureClient:
    def __init__(self, token, cancel):
        self.token = token
        self.cancel = cancel
        self.calls = 0
        self.session = SimpleNamespace(close=lambda: None)

    def search(self, query, limit):
        self.calls += 1
        if query == "fail":
            raise CollectionError("Ошибка " + self.token)
        if query == "cancel":
            raise Cancelled("cancel")
        if query == "interrupt":
            raise KeyboardInterrupt
        if query == "wait":
            print("READY", file=sys.stderr, flush=True)
            threading.Event().wait(60)
        return [{"id": 1, "name": "Новости региона"}, {"id": 2, "name": "Второй источник"}][:limit]

    def call(self, method, **params):
        self.calls += 1
        gid = -params["owner_id"]
        if gid == 98:
            self.cancel.set()
            raise Cancelled("cancel")
        if gid == 99:
            raise CollectionError("Нет доступа")
        start, _ = year_period(2019)
        posts = [{"id": i, "date": start + 86400 * (5 - i),
                  "text": "Экономические новости региона", "is_pinned": 0}
                 for i in range(1, (4 if gid == 1 else 2))]
        offset, count = params["offset"], params["count"]
        return {"count": len(posts), "items": posts[offset:offset + count]}


if __name__ == "__main__":
    from collection_cli import main
    code = main(sys.argv[1:], client_factory=FixtureClient)
    assert "tkinter" not in sys.modules
    assert "customtkinter" not in sys.modules
    assert "tensorflow" not in sys.modules
    raise SystemExit(code)
