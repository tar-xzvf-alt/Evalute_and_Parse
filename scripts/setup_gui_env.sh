#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python_bin="${GUI_PYTHON:-/usr/bin/python3}"
"$python_bin" -c 'import tkinter as t; r=t.Tk(); r.withdraw(); print("Tk font system:", r.tk.call("::tk::pkgconfig", "get", "fontsystem")); r.destroy()'
"$python_bin" -m venv --system-site-packages .venv-gui
.venv-gui/bin/python -m pip install -r requirements-gui.txt
echo 'Готово. Запуск: bash run_gui.sh'
