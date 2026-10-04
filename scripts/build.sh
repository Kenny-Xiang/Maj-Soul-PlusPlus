#!/bin/zsh
set -euo pipefail
cd "${0:A:h:h}"
export PYINSTALLER_CONFIG_DIR="$PWD/build/pyinstaller-cache"
exec .venv/bin/python -m PyInstaller --noconfirm --distpath dist --workpath build/pyinstaller Maj-Soul++.spec
