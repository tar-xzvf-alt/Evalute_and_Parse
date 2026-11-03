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


class WallChanged(CollectionError):
    """Internal signal: pagination must be restarted or re-anchored."""

    def __init__(self, count):
        self.count = count
        super().__init__("Количество записей стены изменилось.")


class VKClient:
    def __init__(self, token, cancel=None):
        if not token.strip():
            raise CollectionError("Не указан токен VK API.")
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
    """One-shot dated wall reader with bounded, anchor-verified head recovery.

    VK does not provide snapshot pagination. Count and page-order checks detect
    common changes, but cannot guarantee a snapshot under simultaneous edits.
    """

    def __init__(self, client, group_id, start, end):
        if start >= end:
            raise CollectionError("Начало периода должно предшествовать концу.")
        self.client = client
        self.group_id = int(group_id)
        self.start, self.end = start, end
        self.recovery_count = 0
        self.first_anchor = None
        self.last_anchor = None
        self.consumed = False
        self._initialize()

    def _budget(self):
        if self.client.cancel.is_set():
            raise Cancelled("Операция отменена.")
        if self.recovery_count >= 3:
            raise CollectionError("Стена слишком часто меняется: исчерпаны 3 попытки восстановления.")
        self.recovery_count += 1

    def _initialize(self):
        while True:
            try:
                self._locate()
                return
            except WallChanged:
                self._budget()

    def _locate(self):
        self.cache = {}
        first = self.client.call("wall.get", owner_id=-self.group_id, offset=0,
                                 count=100, filter="owner")
        self.cache[(0, 100)] = first
        self.total = first["count"]
        self.pinned = [p for p in first["items"] if p.get("is_pinned")]
        if len(self.pinned) > 1 or (self.pinned and not first["items"][0].get("is_pinned")):
            raise CollectionError("Неожиданный порядок закреплённых записей.")
        self.shift = len(self.pinned)
        self.size = self.total - self.shift
        self.head = [p for p in first["items"] if not p.get("is_pinned")]
        self._check_order(self.head)
        self.upper = self._boundary(self.end)
        self.lower = self._boundary(self.start)

    def _request(self, offset, count, fresh=False):
        key = (offset, count)
        if fresh or key not in self.cache:
            result = self.client.call("wall.get", owner_id=-self.group_id,
                                      offset=offset, count=count, filter="owner")
            if hasattr(self, "total") and result["count"] != self.total:
                raise WallChanged(result["count"])
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

    @staticmethod
    def _identity(items):
        return [(p['id'], p['date']) for p in items]

    def _recover(self):
        """Accept only a positive global offset shift confirmed at both anchors."""
        while True:
            self._budget()
            head = self.client.call('wall.get', owner_id=-self.group_id, offset=0,
                                    count=100, filter='owner')
            delta = head['count'] - self.total
            if delta <= 0:
                raise CollectionError("Число записей уменьшилось или сдвиг не подтверждён; восстановление небезопасно.")
            pins = [p for p in head['items'] if p.get('is_pinned')]
            if self._identity(pins) != self._identity(self.pinned):
                raise CollectionError("Закреплённые записи изменились; требуется новый запуск.")
            self._check_order([p for p in head['items'] if not p.get('is_pinned')])
            anchors = [self.first_anchor]
            if self.last_anchor[0] != self.first_anchor[0]:
                anchors.append(self.last_anchor)
            stable = True
            for offset, expected in anchors:
                result = self.client.call('wall.get', owner_id=-self.group_id,
                                          offset=offset + delta, count=len(expected), filter='owner')
                if result['count'] != head['count']:
                    stable = False
                    break
                if self._identity(result['items']) != self._identity(expected):
                    raise CollectionError("Опорные записи не подтверждают сдвиг стены; сбор остановлен.")
            if not stable:
                continue
            self.total = head['count']
            self.cache.clear()
            self.first_anchor = (self.first_anchor[0] + delta, self.first_anchor[1])
            self.last_anchor = (self.last_anchor[0] + delta, self.last_anchor[1])
            return delta

    def posts(self):
        if self.consumed:
            raise CollectionError('Для повторного обхода создайте новый WallPeriod.')
        self.consumed = True
        seen = set()
        previous = None
        remaining = self.lower - self.upper
        offset = self.upper + self.shift
        while remaining:
            overlap = 1 if self.last_anchor else 0
            count = min(100, remaining + overlap)
            try:
                items = self._request(offset - overlap, count, fresh=True)['items']
            except WallChanged:
                if self.first_anchor is None:
                    self._budget()
                    self._initialize()
                    remaining = self.lower - self.upper
                    offset = self.upper + self.shift
                else:
                    offset += self._recover()
                continue
            if len(items) != count:
                raise CollectionError("Получена неполная страница. Результат не считается полным.")
            self._check_order(items)
            if overlap:
                if self._identity(items[:1]) != self._identity(self.last_anchor[1][-1:]):
                    raise CollectionError("Опорная запись между страницами не совпала; возможны пропуски.")
                items = items[1:]
            anchor = (offset, items)
            if self.first_anchor is None:
                self.first_anchor = anchor
            self.last_anchor = anchor
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
            offset += len(items)
            remaining -= len(items)
        # Validate the endpoints again. New head publications can be reconciled,
        # but deletions or unexplained changes must never be silently accepted.
        while True:
            try:
                head = self._request(0, 1, fresh=True)
                pins = [p for p in head['items'] if p.get('is_pinned')]
                if self._identity(pins) != self._identity(self.pinned):
                    raise CollectionError('Закрепление изменилось к завершению сбора.')
                for anchor in (self.first_anchor, self.last_anchor):
                    if anchor is not None:
                        actual = self._request(anchor[0], len(anchor[1]), fresh=True)['items']
                        if self._identity(actual) != self._identity(anchor[1]):
                            raise CollectionError("Опорные записи изменились к завершению сбора.")
                break
            except WallChanged:
                if self.first_anchor is None:
                    raise CollectionError("Пустой участок стены изменился; повторите проверку.") from None
                self._recover()
        for post in self.pinned:
            if self.start <= post['date'] < self.end:
                if post['id'] in seen:
                    raise CollectionError('Закреплённая запись повторилась в истории.')
                yield post


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
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("settings"), dict):
        raise CollectionError("Неподдерживаемый профиль.")
    if not isinstance(data.get("groups"), list):
        raise CollectionError("Профиль должен содержать список groups.")
    seen = set()
    for group in data["groups"]:
        if (not isinstance(group, dict) or type(group.get("id")) is not int
                or group["id"] <= 0 or not isinstance(group.get("name"), str)
                or type(group.get("selected", False)) is not bool):
            raise CollectionError("Некорректное сообщество в профиле.")
        if group["id"] in seen:
            raise CollectionError("Повтор ID сообщества в профиле.")
        seen.add(group["id"])
    return data


def archive_posts(period, path):
    """Keep original text, including filtered-out records and long Excel cells."""
    with Path(path).open("w", encoding="utf-8") as stream:
        for post in period.posts():
            row = {"post_id": post["id"], "group_id": period.group_id,
                   "date": post["date"], "text": post.get("text", "")}
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            yield post


def resume_exports(path, folder, rows, year, keywords, min_words):
    """Verify completed files locally before deciding that a source can be skipped."""
    from openpyxl import load_workbook
    from zipfile import BadZipFile

    root = Path(folder).resolve()
    path = Path(path).resolve()
    if path.parent != root:
        raise CollectionError('Паспорт продолжения должен находиться в папке результатов.')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if (data['year'] != int(year) or data['timezone'] != 'UTC' or data['filter'] != 'owner'
                or data['keywords'] != keywords or data['min_words'] != min_words):
            raise CollectionError('Параметры продолжения отличаются от прежнего запуска.')
        groups = data['groups']
        ids = [group['id'] for group in groups]
        planned = data.get('planned_group_ids', ids)
        if (len(ids) != len(set(ids)) or len(planned) != len(set(planned))
                or not set(ids).issubset(set(planned)) or set(planned) != {row['id'] for row in rows}):
            raise CollectionError('Набор источников продолжения должен совпадать с паспортом.')
        start, end = year_period(year)
        terms = [term.strip().casefold() for term in keywords.split(',') if term.strip()]
        verified = {}
        for group in groups:
            if group['status'] != 'complete':
                continue
            raw_path, excel_path = [(root / group[key]).resolve() for key in ('raw_file', 'file')]
            if any(p.parent != root or not p.is_file() for p in (raw_path, excel_path)):
                raise CollectionError('Не найдены безопасные пути к завершённым файлам.')
            count = 0
            ids = set()
            retained = {}
            with raw_path.open(encoding='utf-8') as stream:
                for line in stream:
                    post = json.loads(line)
                    pid = post['post_id']
                    if (post['group_id'] != group['id'] or pid in ids
                            or not start <= post['date'] < end):
                        raise CollectionError('Завершённый JSONL не прошёл проверку ID/дат.')
                    ids.add(pid)
                    count += 1
                    text = post['text']
                    if text.strip() and len(text.split()) >= min_words and (not terms or any(t in text.casefold() for t in terms)):
                        retained[pid] = post
            book = load_workbook(excel_path, read_only=True)
            try:
                cells = book.active.iter_rows(values_only=True)
                if next(cells, None) != ('text', 'post_id', 'group_id', 'date_utc', 'url'):
                    raise CollectionError('Заголовок завершённого Excel не прошёл проверку.')
                excel_ids = set()
                for text, pid, gid, date, url in cells:
                    if pid not in retained or pid in excel_ids:
                        raise CollectionError('Набор строк завершённого Excel не совпадает с JSONL.')
                    post = retained[pid]
                    clean = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', post['text'])[:32767]
                    if (text != clean or gid != group['id']
                            or date != datetime.fromtimestamp(post['date'], timezone.utc).isoformat()
                            or url != f"https://vk.com/wall-{gid}_{pid}"):
                        raise CollectionError('Содержимое завершённого Excel отличается от JSONL.')
                    excel_ids.add(pid)
                if (count != group['available'] or len(excel_ids) != group['retained']
                        or excel_ids != set(retained)):
                    raise CollectionError('Количество строк завершённых файлов не совпадает с паспортом.')
            finally:
                book.close()
            verified[group['id']] = dict(group, reused=True, reused_from=path.name)
        return verified
    except CollectionError:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError, BadZipFile):
        raise CollectionError('Невозможно проверить паспорт/файлы продолжения.') from None


def export_posts(folder, rows, client, year, keywords="", min_words=0, progress=None, resume_manifest=None):
    from openpyxl import Workbook

    start, end = year_period(year)
    directory = Path(folder)
    if not directory.is_dir():
        raise CollectionError("Выберите существующую папку.")
    reused = resume_exports(resume_manifest, folder, rows, year, keywords, min_words) if resume_manifest else {}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    manifest = {"started_utc": stamp, "year": int(year), "timezone": "UTC",
                "filter": "owner", "keywords": keywords, "min_words": min_words,
                "groups": [], "planned_group_ids": [row['id'] for row in rows], "status": "running"}
    if resume_manifest:
        manifest['resumed_from'] = Path(resume_manifest).name
    manifest_path = directory / f"collection_{stamp}.json"
    terms = [x.strip().casefold() for x in keywords.split(",") if x.strip()]
    active_result = None
    book = sheet = None
    try:
        for group in rows:
            if client.cancel.is_set():
                raise Cancelled('Операция отменена.')
            if group['id'] in reused:
                manifest['groups'].append(reused[group['id']])
                if progress:
                    progress('Проверенные файлы переиспользованы: ' + group['name'])
                continue
            if progress:
                progress(group["name"])
            result = {"id": group["id"], "name": group["name"], "status": "running"}
            active_result = result
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
            result.update(status="complete", available=collected, retained=kept, file=path.name,
                          recovery_count=period.recovery_count,
                          pagination='anchored; first page fixes the upper boundary')
            active_result = None
            book = sheet = None
        manifest["status"] = "complete"
    except BaseException as error:
        if sheet is not None:
            sheet.close()
            book.close()
        manifest["status"] = "cancelled" if client.cancel.is_set() or isinstance(error, KeyboardInterrupt) else "failed"
        if active_result is not None:
            active_result['status'] = manifest['status']
        raise
    finally:
        manifest["api_calls"] = client.calls
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path
