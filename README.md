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
| `TryToParse_new.py` | GUI-приложение (CustomTkinter) — 4 вкладки: парсинг, токены, анализ одного файла, мониторинг папок |
| `parsar.py` | Парсинг VK API (посты, комментарии) |
| `batch_setniment_analyzer.py` | Пакетный словарный анализ тональности по иерархии папок |
| `slovari_script_new.py` | Словарный анализ тональности (один файл) |
| `slovari_parse_itogi.py` | Агрегация статистик тональности в сводный Excel |
| `evaluate_script.py` | SDG-классификация через ruBERT на Excel-файлах |
| `sdg_prepare_script.py` | Разбивка результатов SDG по отдельным классам |
| `analyse.py` | ML-классификация тональности (TF-IDF + Random Forest / KNN) |
| `razmet_script.py` | Матрицы ошибок для сравнения словарей |
| `diag.py` | Визуализация региональных данных |

## Данные

- `data/kartaslovsent.csv` — словарь КартаСловСент (46 тыс. терминов)
- `data/rusentilex.csv` — словарь RuSentiLex (16 тыс. терминов)
- `rubert_bert_RU_35data_6_epochs/` — дообученная модель ruBERT (не в репозитории, скачивается отдельно)

## Запуск

```bash
# GUI
python3 TryToParse_new.py

# SDG классификация (CLI)
python3 evaluate_script.py --input_folder <путь> --threshold 0.9 --batch_size 24

# Пакетный анализ тональности
python3 batch_setniment_analyzer.py

# Агрегация результатов
python3 slovari_parse_itogi.py
```

## Конвейер обработки

```
Парсинг (parsar.py / TryToParse_new.py)
  → Анализ тональности (batch_setniment_analyzer.py / slovari_script_new.py)
    → Агрегация (slovari_parse_itogi.py)
      → SDG-классификация (evaluate_script.py)
        → Разбивка по классам (sdg_prepare_script.py)
```
