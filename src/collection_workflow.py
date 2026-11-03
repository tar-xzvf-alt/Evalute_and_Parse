"""Shared GUI/CLI collection policy; no Tk, network construction or file dialogs."""

from vk_collection import Cancelled, CollectionError, WallPeriod, measure, select_groups, year_period


DEFAULT_SETTINGS = {
    "query": "Омск новости", "year": "2020", "candidates": 20,
    "maximum": 5, "minimum": 100, "min_words": 5, "keywords": "",
    "folder": "", "mode": "Вручную",
}


def normalize_settings(settings):
    result = {key: settings.get(key, value) for key, value in DEFAULT_SETTINGS.items()}
    for key in ("query", "keywords", "folder", "mode"):
        if not isinstance(result[key], str):
            raise CollectionError(f"Параметр {key} должен быть строкой.")
        result[key] = result[key].strip()
    try:
        if isinstance(result["year"], (bool, float)):
            raise ValueError
        year_period(result["year"])
        result["year"] = str(int(result["year"]))
    except (ValueError, TypeError, OverflowError):
        raise CollectionError("Укажите корректный год.") from None
    for key, low, high in (("candidates", 1, 1000), ("maximum", 1, 1000),
                           ("minimum", 0, 100000000), ("min_words", 0, 100000)):
        value = result[key]
        try:
            if isinstance(value, (bool, float)):
                raise ValueError
            value = int(value)
        except (ValueError, TypeError, OverflowError):
            raise CollectionError(f"Параметр {key} должен быть целым числом.") from None
        if not low <= value <= high:
            raise CollectionError(f"Параметр {key}: допустимо от {low} до {high}.")
        result[key] = value
    return result


def search_groups(client, settings):
    settings = normalize_settings(settings)
    return [{"id": g["id"], "name": g["name"], "selected": False}
            for g in client.search(settings["query"], settings["candidates"])]


def assess_groups(client, settings, rows, exact=False, automatic=False, progress=None):
    """Mutate supplied rows, preserving GUI selection unless automatic is explicit.

    Per-source errors remain in results so CLI can write partial output and return
    a nonzero status. Cancellation aborts rather than masquerading as an error row.
    """
    settings = normalize_settings(settings)
    start, end = year_period(settings["year"])
    for row in rows:
        if client.cancel.is_set():
            raise Cancelled("Операция отменена.")
        if progress:
            progress("Проверка: " + row["name"])
        row.pop("error", None)
        row.pop("months", None)
        row.update(verified=False, count=None, year=settings["year"])
        try:
            period = WallPeriod(client, row["id"], start, end)
            row["count"] = period.estimate()
            near = abs(row["count"] - settings["minimum"]) <= max(10, settings["minimum"] * .1)
            if exact or (automatic and (near or row["count"] >= settings["minimum"])):
                row["count"], row["months"] = measure(period)
                row["verified"] = True
            row["status"] = "Проверено" if row["verified"] else "Оценка по границам"
        except Cancelled:
            raise
        except CollectionError as error:
            row.update(error=str(error), status=str(error), count=None)
    if automatic:
        chosen = {row["id"] for row in select_groups(rows, settings["maximum"], settings["minimum"])}
        for row in rows:
            row["selected"] = row["id"] in chosen
            if not row.get("error"):
                row["status"] = ("Выбрано по активности" if row["selected"] else
                                 "Ниже порога" if row["count"] < settings["minimum"] else "За пределами K")
    return rows
