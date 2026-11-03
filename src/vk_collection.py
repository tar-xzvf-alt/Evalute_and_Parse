"""VK collection independent of Tk: dated wall access, selection and exports."""

import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


class CollectionError(Exception):
    pass


class Cancelled(CollectionError):
    pass


class VKClient:
    def __init__(self, token, cancel=None):
        if not token.strip():
            raise CollectionError("Укажите токен на вкладке «API Токен».")
        self.token = token.strip()
        self.cancel = cancel or threading.Event()
        self.session = requests.Session()
        self.calls = 0
        self.last_call = 0

    def call(self, method, **params):
        for attempt in range(4):
            if self.cancel.wait(max(0, .4 - (time.monotonic() - self.last_call))):
                raise Cancelled("Операция отменена.")
            self.last_call = time.monotonic()
            self.calls += 1
            try:
                response = self.session.post(
                    "https://api.vk.com/method/" + method,
                    data={**params, "v": "5.131", "access_token": self.token},
                    timeout=25,
                )
                response.raise_for_status()
                data = response.json()
            except (requests.RequestException, ValueError):
                if attempt == 3:
                    raise CollectionError("Сеть/API недоступны. Повторите операцию.") from None
                if self.cancel.wait(2 ** attempt):
                    raise Cancelled("Операция отменена.")
                continue
            if "error" not in data:
                if "response" not in data:
                    raise CollectionError("Некорректный ответ VK.")
                return data["response"]
            code = data["error"].get("error_code")
            if code in (6, 9, 10, 29) and attempt < 3:
                if self.cancel.wait(2 ** (attempt + 1)):
                    raise Cancelled("Операция отменена.")
                continue
            # Do not propagate response parameters or credential-bearing URLs.
            raise CollectionError(f"VK: ошибка {code}. Проверьте токен и доступ к источнику.")
        raise CollectionError("Не удалось выполнить запрос.")

    def search(self, query, limit):
        if not query.strip() or not 1 <= limit <= 1000:
            raise CollectionError("Укажите запрос и число кандидатов от 1 до 1000.")
        groups = {}
        offset = 0
        while offset < limit:
            result = self.call("groups.search", q=query, type="page", sort=0,
                               offset=offset, count=min(100, limit - offset))
            items = result.get("items", [])
            if not items:
                break
            for group in items:
                groups[group["id"]] = group
            offset += len(items)
        return list(groups.values())


def year_period(year):
    """Explicit UTC boundaries; the GUI labels this timezone."""
    year = int(year)
    if not 1970 <= year <= 9998:
        raise CollectionError("Год должен быть в диапазоне 1970–9998.")
    return (int(datetime(year, 1, 1, tzinfo=timezone.utc).timestamp()),
            int(datetime(year + 1, 1, 1, tzinfo=timezone.utc).timestamp()))


class WallPeriod:
    """Locate a date interval in a stable descending wall; fail on detected drift.

    VK does not provide snapshot pagination. Count and page-order checks detect
    common changes, but cannot guarantee a snapshot under simultaneous edits.
    """

    def __init__(self, client, group_id, start, end):
        if start >= end:
            raise CollectionError("Начало периода должно предшествовать концу.")
        self.client = client
        self.group_id = int(group_id)
        self.start, self.end = start, end
        self.cache = {}
        first = self._request(0, 100)
        self.total = first["count"]
        self.pinned = [p for p in first["items"] if p.get("is_pinned")]
        if len(self.pinned) > 1 or (self.pinned and not first["items"][0].get("is_pinned")):
            raise CollectionError("Неожиданный порядок закреплённых записей.")
        self.shift = len(self.pinned)
        self.size = self.total - self.shift
        self.head = [p for p in first["items"] if not p.get("is_pinned")]
        self._check_order(self.head)
        self.upper = self._boundary(end)
        self.lower = self._boundary(start)

    def _request(self, offset, count):
        key = (offset, count)
        if key not in self.cache:
            result = self.client.call("wall.get", owner_id=-self.group_id,
                                      offset=offset, count=count, filter="owner")
            if hasattr(self, "total") and result["count"] != self.total:
                raise CollectionError("Стена изменилась во время обработки. Повторите проверку.")
            self.cache[key] = result
        return self.cache[key]

    @staticmethod
    def _check_order(items):
        if any(a["date"] < b["date"] for a, b in zip(items, items[1:])):
            raise CollectionError("Порядок дат нарушен; быстрый поиск не гарантирует полноту.")

    def _boundary(self, timestamp):
        # Recent intervals can be located directly in the first fetched page.
        # This avoids logarithmic probes when a sequential reader needs one page.
        for index, post in enumerate(self.head):
            if post["date"] < timestamp:
                return index
        if len(self.head) == self.size:
            return self.size
        lo, hi = 0, self.size
        while lo < hi:
            mid = (lo + hi) // 2
            items = self._request(mid + self.shift, 1)["items"]
            if not items:
                raise CollectionError("Неполная история стены: смещение недоступно.")
            if items[0].get("is_pinned"):
                raise CollectionError("Закреплённая запись встретилась внутри истории.")
            if items[0]["date"] < timestamp:
                hi = mid
            else:
                lo = mid + 1
        # Verify both sides, including duplicate timestamps exactly on a boundary.
        for index in (lo - 1, lo):
            if 0 <= index < self.size:
                items = self._request(index + self.shift, 1)["items"]
                if not items or ((items[0]["date"] >= timestamp) != (index < lo)):
                    raise CollectionError("Граница периода нестабильна. Повторите проверку.")
        return lo

    def estimate(self):
        pins = sum(self.start <= p["date"] < self.end for p in self.pinned)
        return self.lower - self.upper + pins

    def posts(self):
        seen = set()
        previous = None
        for post in self.pinned:
            if self.start <= post["date"] < self.end:
                seen.add(post["id"])
                yield post
        for offset in range(self.upper, self.lower, 100):
            count = min(100, self.lower - offset)
            items = self._request(offset + self.shift, count)["items"]
            if len(items) != count:
                raise CollectionError("Получена неполная страница. Результат не считается полным.")
            self._check_order(items)
            for post in items:
                if post.get("is_pinned") or not self.start <= post["date"] < self.end:
                    raise CollectionError("История изменилась: запись вне найденного периода.")
                if previous is not None and previous < post["date"]:
                    raise CollectionError("Порядок страниц нарушен.")
                previous = post["date"]
                if post["id"] in seen:
                    raise CollectionError("Повтор записи: смещения стены изменились.")
                seen.add(post["id"])
                yield post
        # Fresh count check, bypassing the local cache.
        final = self.client.call("wall.get", owner_id=-self.group_id, offset=0,
                                 count=1, filter="owner")
        if final["count"] != self.total:
            raise CollectionError("Стена изменилась до завершения выгрузки.")


def measure(period):
    months = [0] * 12
    count = 0
    for post in period.posts():
        months[datetime.fromtimestamp(post["date"], timezone.utc).month - 1] += 1
        count += 1
    return count, months


def select_groups(rows, maximum, minimum):
    eligible = [row for row in rows if row.get("count") is not None
                and row["count"] >= minimum and not row.get("error")]
    return sorted(eligible, key=lambda row: (-row["count"], row["id"]))[:maximum]


def save_profile(path, settings, groups):
    # Explicit allow-list prevents credentials/results leaking into shared profiles.
    keys = ("query", "year", "candidates", "maximum", "minimum", "keywords",
            "min_words", "folder", "mode")
    data = {"version": 1, "settings": {k: settings[k] for k in keys if k in settings},
            "groups": [{"id": int(g["id"]), "name": str(g["name"]),
                        "selected": bool(g.get("selected"))} for g in groups]}
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_profile(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("version") != 1 or not isinstance(data.get("settings"), dict):
        raise CollectionError("Неподдерживаемый профиль.")
    for group in data["groups"]:
        if type(group["id"]) is not int or group["id"] <= 0 or not isinstance(group["name"], str):
            raise CollectionError("Некорректное сообщество в профиле.")
    return data


def archive_posts(period, path):
    """Keep original text, including filtered-out records and long Excel cells."""
    with Path(path).open("w", encoding="utf-8") as stream:
        for post in period.posts():
            row = {"post_id": post["id"], "group_id": period.group_id,
                   "date": post["date"], "text": post.get("text", "")}
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            yield post


def export_posts(folder, rows, client, year, keywords="", min_words=0, progress=None):
    from openpyxl import Workbook

    start, end = year_period(year)
    directory = Path(folder)
    if not directory.is_dir():
        raise CollectionError("Выберите существующую папку.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    manifest = {"started_utc": stamp, "year": int(year), "timezone": "UTC",
                "filter": "owner", "keywords": keywords, "min_words": min_words,
                "groups": [], "status": "running"}
    manifest_path = directory / f"collection_{stamp}.json"
    terms = [x.strip().casefold() for x in keywords.split(",") if x.strip()]
    try:
        for group in rows:
            if progress:
                progress(group["name"])
            result = {"id": group["id"], "name": group["name"], "status": "running"}
            manifest["groups"].append(result)
            raw_path = directory / f"VK_{group['id']}_{year}_{stamp}.jsonl"
            result["raw_file"] = raw_path.name
            book = Workbook(write_only=True)
            sheet = book.create_sheet("Публикации")
            # Existing dictionary analysis uses read_excel() and column A.
            sheet.append(["text", "post_id", "group_id", "date_utc", "url"])
            collected = kept = 0
            period = WallPeriod(client, group["id"], start, end)
            for post in archive_posts(period, raw_path):
                collected += 1
                text = post.get("text", "")
                if len(text.split()) < min_words or not text.strip():
                    continue
                if terms and not any(term in text.casefold() for term in terms):
                    continue
                text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
                # Write as a literal string, including text beginning with '='.
                from openpyxl.cell import WriteOnlyCell
                cell = WriteOnlyCell(sheet, value=text[:32767])
                cell.data_type = "s"
                sheet.append([cell, post["id"], group["id"],
                              datetime.fromtimestamp(post["date"], timezone.utc).isoformat(),
                              f"https://vk.com/wall-{group['id']}_{post['id']}"])
                kept += 1
            path = directory / f"VK_{group['id']}_{year}_посты_{stamp}.xlsx"
            book.save(path)
            result.update(status="complete", available=collected, retained=kept, file=path.name)
        manifest["status"] = "complete"
    except Exception:
        if "sheet" in locals():
            sheet.close()
            book.close()
        manifest["status"] = "cancelled" if client.cancel.is_set() else "failed"
        if manifest["groups"]:
            manifest["groups"][-1]["status"] = manifest["status"]
        raise
    finally:
        manifest["api_calls"] = client.calls
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path
