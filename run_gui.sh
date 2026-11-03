#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ -x .venv-gui/bin/python ]]; then
    exec .venv-gui/bin/python src/TryToParse_new.py
elif [[ -x myenv/bin/python ]]; then
    echo 'Используется старое окружение. При пиксельных шрифтах: bash scripts/setup_gui_env.sh' >&2
    exec myenv/bin/python src/TryToParse_new.py
else
    echo 'Сначала выполните: bash scripts/setup_gui_env.sh' >&2
    exit 1
fi
