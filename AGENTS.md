# AGENTS.md

## What this is
Russian VK social media parser + dictionary-based sentiment analysis (Kartaslovsent, RuSentiLex) + ruBERT-based SDG classification (17 UN goals). GUI app (`TryToParse_new.py`) wraps all functionality.

## Setup
```bash
pip install -r requirements02022026.txt
```
Python 3.10 required — TensorFlow 2.10.1 and `tensorflow-addons` are pinned and won't install on newer Python.

No build system, no linter, no typechecker, no tests. Just direct `python script.py` invocations.

## Entrypoints

| Script | Purpose | Args |
|---|---|---|
| `TryToParse_new.py` | GUI app (CustomTkinter) — 4 tabs: parsing, token mgmt, single-file analysis, multi-folder analysis | none |
| `evaluate_script.py` | Batch SDG classification via ruBERT on Excel files | `--input_folder <path>` (required), `--threshold 0.9`, `--batch_size 24`, `--model_path rubert_bert_RU_35data_6_epochs/`, etc. |
| `batch_setniment_analyzer.py` | Batch dictionary sentiment analysis on folder hierarchies | none (hardcoded paths inside) |
| `slovari_parse_itogi.py` | Aggregate per-file sentiment stats into master Excel | none |
| `analyse.py` | ML sentiment (TF-IDF + Random Forest/KNN) | needs `combcombcomb.xlsx` and `comb_test_1.xlsx` — **not in repo** |
| `sdg_prepare_script.py` | Split SDG-classified Excel into per-class files | none |
| `razmet_script.py` | Confusion matrix charts for dictionary comparison | none |
| `diag.py` | Regional data charts from multi-sheet Excel | none |

## Architecture & quirks

### PyInstaller compatibility
`parsar.py`, `batch_setniment_analyzer.py`, `slovari_script_new.py`, and `TryToParse_new.py` all define `resource_path()` using `sys._MEIPASS`. The project was designed to be packaged as a Windows `.exe`. File paths resolved via this function need to work both in dev and in bundled builds.

### VK API tokens — exposed
A real VK API token is hardcoded in `parsar.py:63` and stored in `vk_token.txt` (not in `.gitignore`). **Never commit new tokens.** The GUI app reads/writes `vk_token.txt` at runtime.

### Sentiment dictionaries — two formats
- **`data/kartaslovsent.csv`** — semicolon-delimited, columns: `term;tag;value;...`, uses fractional `value` (e.g. `0.08`, `-0.68`)
- **`data/rusentilex.csv`** — comma-delimited, columns: `term,value`, binary-ish (`-1`, `0`, `1`)

Both are looked up via `resource_path()` — do not move or rename them without updating `slovari_script_new.py` and `batch_setniment_analyzer.py`.

### SDG model
`rubert_bert_RU_35data_6_epochs/` is a TensorFlow SavedModel (not HuggingFace format). `evaluate_script.py` tries two loading methods: (1) `tf.keras.models.load_model` with custom_objects for `tfa`, (2) `create_model()` + `load_weights()`. Both attempt to use `DeepPavlov/rubert-base-cased` as the base. Model is gitignored — must be downloaded/placed manually.

### Data flow
```
Parsing (parsar.py / TryToParse_new.py)
  → Sentiment analysis (batch_setniment_analyzer.py / slovari_script_new.py)
    → Aggregation (slovari_parse_itogi.py)
      → SDG classification (evaluate_script.py)
        → Split by SDG class (sdg_prepare_script.py)
```

### Output naming convention
`{Region}_{year}_{content_type}_{filtered}_{timestamp}.xlsx`
Example: `Астраханская область_посты_2020_filtered_20260219_011341.xlsx`

### `.gitignore` coverage
`vk_token.txt`, `*.log`, `*.pkl`, `*.xlsx`, `*.zip`, `predictions.csv`, `TEST.csv`, and all result/output directories are gitignored. The only committed data files are the two sentiment dictionaries.

### analyse.py dependencies
Requires `combcombcomb.xlsx` and `comb_test_1.xlsx` — these files are **not in the repo** and must be provided externally. Saves models as `random_forest_model.pkl`, `knn_model.pkl`, `tfidf_vectorizer.pkl`.
