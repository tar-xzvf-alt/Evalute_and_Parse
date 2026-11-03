# AGENTS.md

## What this is
Russian VK social media parser + dictionary-based sentiment analysis (Kartaslovsent, RuSentiLex) + ruBERT-based SDG classification (17 UN goals). GUI app (`src/TryToParse_new.py`) wraps all functionality.

## Setup
For the GUI on Linux use `bash scripts/setup_gui_env.sh`, then `bash run_gui.sh`. This creates a separate `.venv-gui` using system Tk/Xft; `myenv` was built with non-antialiased X11 fonts. Read `docs/vk-collection.md` for runtime details. GUI dependencies are in `requirements-gui.txt`.

For the TensorFlow SDG model / legacy ML environment:
```bash
pip install -r requirements02022026.txt
```
Python 3.10 required — TensorFlow 2.10.1 and `tensorflow-addons` are pinned and won't install on newer Python.

No build system, no linter, no typechecker. Collection regression tests: `.venv-gui/bin/python -m unittest discover -s tests -v` (or the configured Python environment). Entrypoints use direct `python script.py` invocations.

For the new collection workbench, profile format, UTC date boundaries, and export files, read `docs/vk-collection.md`. `src/vk_collection.py` is the Tk-independent backend; `src/collection_ui.py` is the queue-driven GUI panel.

For headless collection commands or automation, read `docs/cli.md`. Run `python -m parsevk` from the repo root (minimal dependencies: `requirements-cli.txt`). `src/collection_workflow.py` owns shared GUI/CLI validation, assessment and automatic selection; keep these rules out of frontend-specific code. CLI regression tests inject a fake client in subprocesses, never real credentials/network. CLI must not import Tk, GUI widgets, NLTK or TensorFlow.

## Entrypoints

| Script | Purpose | Args |
|---|---|---|
| `parsevk.py` / `python -m parsevk` | Headless VK collection: search, assess, verify, select, collect, run saved GUI profiles | `--help`; see `docs/cli.md` |
| `src/TryToParse_new.py` | GUI app (CustomTkinter) — collection workbench, legacy collection/comments, token mgmt, single-file analysis, multi-folder analysis | none |
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

### VK API tokens
The GUI reads/writes the gitignored `vk_token.txt` at runtime. The old hardcoded post-collection token was removed; treat any credentials in Git history as exposed. **Never commit tokens or include them in exported profiles, diagnostics, or manifests.**

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

### Repository scope
LaTeX papers, research reading notes, and thesis-planning material were moved to an external local archive at the user's request. Keep application code, tests, dictionaries, and operational documentation here; do not restore research PDFs or build artifacts as application assets.
