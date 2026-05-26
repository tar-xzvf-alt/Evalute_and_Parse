# ParseVK — анализ социальных медиа ВКонтакте

Инструментарий для парсинга постов и комментариев ВКонтакте, словарного анализа тональности (КартаСловСент, RuSentiLex) и классификации по целям устойчивого развития ООН с помощью ruBERT.

## Установка

```bash
pip install -r requirements02022026.txt
```

Требуется Python 3.10.

## Состав

| Скрипт | Назначение |
|---|---|
| `src/TryToParse_new.py` | GUI-приложение (CustomTkinter) — 4 вкладки: парсинг, токены, анализ одного файла, мониторинг папок |
| `src/parsar.py` | Парсинг VK API (посты, комментарии) |
| `src/batch_setniment_analyzer.py` | Пакетный словарный анализ тональности по иерархии папок |
| `src/slovari_script_new.py` | Словарный анализ тональности (один файл) |
| `src/slovari_parse_itogi.py` | Агрегация статистик тональности в сводный Excel |
| `src/evaluate_script.py` | SDG-классификация через ruBERT на Excel-файлах |
| `src/sdg_prepare_script.py` | Разбивка результатов SDG по отдельным классам |
| `src/analyse.py` | ML-классификация тональности (TF-IDF + Random Forest / KNN) |
| `src/razmet_script.py` | Матрицы ошибок для сравнения словарей |
| `src/diag.py` | Визуализация региональных данных |

## Данные

- `data/kartaslovsent.csv` — словарь КартаСловСент (46 тыс. терминов)
- `data/rusentilex.csv` — словарь RuSentiLex (16 тыс. терминов)
- `rubert_bert_RU_35data_6_epochs/` — дообученная модель ruBERT (не в репозитории, скачивается отдельно)

## Запуск

```bash
# GUI
python src/TryToParse_new.py

# SDG классификация (CLI)
python src/evaluate_script.py --input_folder <путь> --threshold 0.9 --batch_size 24

# Пакетный анализ тональности
python src/batch_setniment_analyzer.py

# Агрегация результатов
python src/slovari_parse_itogi.py
```

## Конвейер обработки

```
Парсинг (src/parsar.py / src/TryToParse_new.py)
  → Анализ тональности (src/batch_setniment_analyzer.py / src/slovari_script_new.py)
    → Агрегация (src/slovari_parse_itogi.py)
      → SDG-классификация (src/evaluate_script.py)
        → Разбивка по классам (src/sdg_prepare_script.py)
```
