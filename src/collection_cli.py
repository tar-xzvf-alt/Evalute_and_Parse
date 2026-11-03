"""Non-interactive collection commands. stdout is JSON; stderr is diagnostics."""

import argparse
import json
import os
import signal
import sys
import tempfile
import threading
from pathlib import Path

from collection_workflow import assess_groups, normalize_settings, search_groups
from vk_collection import Cancelled, CollectionError, VKClient, export_posts, load_profile, save_profile


def parser():
    root = argparse.ArgumentParser(prog="parsevk", description="Сбор VK без GUI. Все периоды — UTC.")
    commands = root.add_subparsers(dest="command", required=True)
    for name, description in (
            ("search", "Найти сообщества"), ("assess", "Оценить годовую активность"),
            ("verify", "Пересчитать год и месяцы"), ("select", "Выбрать источники по активности"),
            ("collect", "Собрать выбранные источники"), ("run", "Собрать сохранённый профиль")):
        command = commands.add_parser(name, help=description, description=description)
        command.add_argument("--token-file", type=Path, help="Файл токена; иначе VK_TOKEN или ./vk_token.txt")
        command.add_argument("--quiet", action="store_true", help="Без сообщений прогресса")
        if name == "search":
            command.add_argument("--query", required=True)
            command.add_argument("--limit", dest="candidates", type=int, default=20)
        if name in ("assess", "verify", "select"):
            command.add_argument("--input", "--profile", dest="input", type=Path, required=True,
                                 help="JSON поиска/оценки или профиль GUI")
        if name in ("collect", "run"):
            source = command.add_mutually_exclusive_group(required=True)
            source.add_argument("--profile", type=Path, help="Профиль GUI или JSON команды select")
            if name == "collect":
                source.add_argument("--groups", help="Положительные ID через запятую; выбрать все указанные")
            command.add_argument("--keywords", help="Буквальные фразы через запятую (ИЛИ)")
            command.add_argument("--min-words", type=int)
            command.add_argument("--output", dest="folder", type=Path, help="Папка корпуса (иначе из профиля)")
            command.add_argument("--report", default="-", help="JSON-итог команды; '-' — stdout")
            command.add_argument("--resume", type=Path,
                                 help="Паспорт прежнего запуска: проверить и переиспользовать завершённые источники")
        else:
            command.add_argument("--output", default="-", help="JSON-результат; '-' — stdout")
        if name != "search":
            command.add_argument("--year", help="Переопределить год, сохранив набор источников")
        if name == "select":
            command.add_argument("--maximum", type=int, help="Не более K источников")
            command.add_argument("--minimum", type=int, help="Минимум N постов за год")
        if name in ("search", "assess", "verify", "select"):
            command.add_argument("--save-profile", type=Path, help="Также сохранить профиль для GUI")
    return root


def write_json(destination, data):
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if destination == "-":
        sys.stdout.write(text)
        return
    path = Path(destination)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".parsevk-", delete=False) as stream:
            temporary = stream.name
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if temporary and Path(temporary).exists():
            Path(temporary).unlink()


def read_token(path):
    if path is not None:
        token = path.read_text(encoding="utf-8").strip()
    else:
        token = os.environ.get("VK_TOKEN", "").strip()
        if not token and Path("vk_token.txt").is_file():
            token = Path("vk_token.txt").read_text(encoding="utf-8").strip()
    if not token:
        raise CollectionError("Укажите VK_TOKEN или --token-file; токен аргументом не принимается.")
    return token


def inputs(args):
    """Validate local inputs before constructing a client or touching the network."""
    settings = {}
    rows = []
    profile = getattr(args, "profile", None) or getattr(args, "input", None)
    if profile:
        data = load_profile(profile)
        settings = data["settings"]
        rows = data["groups"]
    if getattr(args, "groups", None):
        try:
            ids = [int(item.strip()) for item in args.groups.split(",")]
            if not ids or any(item <= 0 for item in ids) or len(ids) != len(set(ids)):
                raise ValueError
        except ValueError:
            raise CollectionError("--groups: укажите уникальные положительные ID через запятую.") from None
        rows = [{"id": item, "name": f"VK {item}", "selected": True} for item in ids]
    for key in ("query", "year", "candidates", "maximum", "minimum", "keywords", "min_words", "folder"):
        value = getattr(args, key, None)
        if value is not None:
            settings[key] = str(value) if isinstance(value, Path) else value
    if args.command != "search" and not settings.get("year"):
        raise CollectionError("Укажите --year или год в профиле.")
    settings = normalize_settings(settings)
    if len(rows) > 1000:
        raise CollectionError("За один запуск допускается не более 1000 источников.")
    if args.command == "search" and not settings["query"]:
        raise CollectionError("Поисковый запрос не должен быть пустым.")
    if args.command in ("collect", "run"):
        if not any(row.get("selected") for row in rows):
            raise CollectionError("Нет выбранных источников. Используйте select, GUI или --groups.")
        if not settings["folder"] or not Path(settings["folder"]).is_dir():
            raise CollectionError("Укажите существующую папку через --output или профиль.")
        if args.resume and not args.resume.is_file():
            raise CollectionError('Не найден паспорт --resume.')
    # Do not spend API calls if a destination directory is invalid.
    output = getattr(args, "report", getattr(args, "output", "-"))
    destinations = [destination for destination in (output, getattr(args, "save_profile", None))
                    if destination is not None and str(destination) != "-"]
    resolved = [Path(destination).resolve() for destination in destinations]
    if len(resolved) != len(set(resolved)):
        raise CollectionError("Результат и профиль должны записываться в разные файлы.")
    token_path = (args.token_file or Path("vk_token.txt")).resolve()
    if token_path in resolved:
        raise CollectionError("Выходной файл не должен заменять файл токена.")
    resume_path = getattr(args, 'resume', None)
    if resume_path and resume_path.resolve() in resolved:
        raise CollectionError('Итог команды не должен заменять исходный паспорт --resume.')
    for destination in destinations:
        if destination is not None and str(destination) != "-":
            if not Path(destination).parent.is_dir() or Path(destination).is_dir():
                raise CollectionError("Некорректный путь выходного JSON/профиля.")
    return settings, rows


def main(argv=None, client_factory=None):
    args = parser().parse_args(argv)
    token = ""
    client = None
    cancel = threading.Event()
    previous_signals = {}
    cancel_code = 130

    def diagnostic(text):
        if not args.quiet:
            print(text.replace(token, "[скрыто]") if token else text, file=sys.stderr)

    def interrupted(signum, frame):
        nonlocal cancel_code
        cancel_code = 128 + signum
        cancel.set()
        raise Cancelled("Операция отменена пользователем.")

    try:
        try:
            settings, rows = inputs(args)
            token = read_token(args.token_file)
        except (CollectionError, ValueError, TypeError, KeyError, OSError) as error:
            print(f"Параметры: {error}", file=sys.stderr)
            return 2
        if threading.current_thread() is threading.main_thread():
            for signum in (signal.SIGINT, signal.SIGTERM):
                previous_signals[signum] = signal.signal(signum, interrupted)
        client = (client_factory or VKClient)(token, cancel)
        if args.command in ("collect", "run"):
            # Deliberately ignore mode=automatic: run never reselects sources.
            manifest = export_posts(settings["folder"], [r for r in rows if r.get("selected")],
                                    client, settings["year"], settings["keywords"], settings["min_words"],
                                    lambda name: diagnostic("Сбор: " + name), resume_manifest=args.resume)
            write_json(args.report, {"status": "complete", "manifest": str(manifest), "api_calls": client.calls})
            return 0
        if args.command == "search":
            rows = search_groups(client, settings)
        else:
            rows = assess_groups(client, settings, rows, exact=args.command == "verify",
                                 automatic=args.command == "select", progress=diagnostic)
        partial = any(row.get("error") for row in rows)
        # The envelope also acts as a GUI-compatible profile. Only known fields
        # are emitted; arbitrary fields supplied by input documents are dropped.
        keys = ("id", "name", "selected", "count", "verified", "months", "year", "status", "error")
        output_settings = dict(settings)
        if args.command == "search":
            # A search has no time period. Do not silently assign its future
            # assessment the GUI's default year.
            output_settings.pop("year", None)
        result = {"version": 1, "settings": output_settings,
                  "groups": [{key: row[key] for key in keys if key in row} for row in rows],
                  "status": "partial" if partial else "complete", "api_calls": client.calls}
        write_json(args.output, result)
        if args.save_profile:
            save_profile(args.save_profile, output_settings, rows)
        return 4 if partial else 0
    except (Cancelled, KeyboardInterrupt):
        cancel.set()
        print("Операция отменена. Проверьте статусы уже созданных файлов.", file=sys.stderr)
        return cancel_code
    except CollectionError as error:
        print(f"API/сбор: {str(error).replace(token, '[скрыто]') if token else error}", file=sys.stderr)
        return 3
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f"Файлы/данные: {str(error).replace(token, '[скрыто]') if token else error}", file=sys.stderr)
        return 1
    finally:
        for signum, handler in previous_signals.items():
            signal.signal(signum, handler)
        if client is not None:
            client.session.close()
