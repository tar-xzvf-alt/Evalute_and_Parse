# AGENTS.md

## What this is
Russian VK social media parser + dictionary-based sentiment analysis (Kartaslovsent, RuSentiLex) + ruBERT-based SDG classification (17 UN goals). GUI app (`src/TryToParse_new.py`) wraps all functionality.

## Setup
```bash
pip install -r requirements02022026.txt
```
Python 3.10 required — TensorFlow 2.10.1 and `tensorflow-addons` are pinned and won't install on newer Python.

No build system, no linter, no typechecker, no tests. Just direct `python script.py` invocations.

## Entrypoints

| Script | Purpose | Args |
|---|---|---|
| `src/TryToParse_new.py` | GUI app (CustomTkinter) — 4 tabs: parsing, token mgmt, single-file analysis, multi-folder analysis | none |
| `src/evaluate_script.py` | Batch SDG classification via ruBERT on Excel files | `--input_folder <path>` (required), `--threshold 0.9`, `--batch_size 24`, `--model_path rubert_bert_RU_35data_6_epochs/`, etc. |
| `src/batch_setniment_analyzer.py` | Batch dictionary sentiment analysis on folder hierarchies | none (hardcoded paths inside) |
| `src/slovari_parse_itogi.py` | Aggregate per-file sentiment stats into master Excel | none |
| `src/analyse.py` | ML sentiment (TF-IDF + Random Forest/KNN) | needs `combcombcomb.xlsx` and `comb_test_1.xlsx` — **not in repo** |
| `src/sdg_prepare_script.py` | Split SDG-classified Excel into per-class files | none |
| `src/razmet_script.py` | Confusion matrix charts for dictionary comparison | none |
| `src/diag.py` | Regional data charts from multi-sheet Excel | none |
| `src/sdg_economic_analysis.py` | Group SDG-classified texts into social/economic/environmental categories, plot distribution | reads from `data/results_filtered/` |
| `src/sdg_sentiment_cross.py` | Compute sentiment per SDG category per region/year, compare dictionaries | reads from `data/results_filtered/`, uses `data/kartaslovsent.csv`, `data/rusentilex.csv` |

## Architecture & quirks

### PyInstaller compatibility
`parsar.py`, `batch_setniment_analyzer.py`, `slovari_script_new.py`, and `TryToParse_new.py` all define `resource_path()` using `sys._MEIPASS`. The project was designed to be packaged as a Windows `.exe`. File paths resolved via this function need to work both in dev and in bundled builds.

### VK API tokens — exposed
A real VK API token is hardcoded in `src/parsar.py:63` and stored in `vk_token.txt` (not in `.gitignore`). **Never commit new tokens.** The GUI app reads/writes `vk_token.txt` at runtime.

### Sentiment dictionaries — two formats
- **`data/kartaslovsent.csv`** — semicolon-delimited, columns: `term;tag;value;...`, uses fractional `value` (e.g. `0.08`, `-0.68`)
- **`data/rusentilex.csv`** — comma-delimited, columns: `term,value`, binary-ish (`-1`, `0`, `1`)

Both are looked up via `resource_path()` — do not move or rename them without updating `slovari_script_new.py` and `batch_setniment_analyzer.py`.

### SDG model
`rubert_bert_RU_35data_6_epochs/` is a TensorFlow SavedModel (not HuggingFace format). `evaluate_script.py` tries two loading methods: (1) `tf.keras.models.load_model` with custom_objects for `tfa`, (2) `create_model()` + `load_weights()`. Both attempt to use `DeepPavlov/rubert-base-cased` as the base. Model is gitignored — must be downloaded/placed manually.

### Data flow
```
Parsing (src/parsar.py / src/TryToParse_new.py)
  → Sentiment analysis (src/batch_setniment_analyzer.py / src/slovari_script_new.py)
    → Aggregation (src/slovari_parse_itogi.py)
      → SDG classification (src/evaluate_script.py)
        → Split by SDG class (src/sdg_prepare_script.py)
```

### Output naming convention
`{Region}_{year}_{content_type}_{filtered}_{timestamp}.xlsx`
Example: `Астраханская область_посты_2020_filtered_20260219_011341.xlsx`

### `.gitignore` coverage
`vk_token.txt`, `*.log`, `*.pkl`, `*.xlsx`, `*.zip`, `predictions.csv`, `TEST.csv`, and all result/output directories are gitignored. The only committed data files are the two sentiment dictionaries.

### analyse.py dependencies
Requires `combcombcomb.xlsx` and `comb_test_1.xlsx` — these files are **not in the repo** and must be provided externally. Saves models as `random_forest_model.pkl`, `knn_model.pkl`, `tfidf_vectorizer.pkl`.

### LaTeX (курсовая магистра)
`Latex/NIRLaTeX/` — курсовая работа магистратуры. Сборка: `latexmk -pdf` (читает `latexmkrc`). Класс документа: `SCWorks1.cls` (СГУ, шаблон КНиИТ). Стиль библиографии: ГОСТ 2003 (`ugost2003.bst`, локальная исправленная копия). `References.bib` — пустой шаблон, `References_old.bib` — эталон оформления из диплома бакалавра.
