#!/bin/zsh
set -euo pipefail
cd "${0:A:h:h}"
node legacy/build.cjs
node --test tests/test.cjs
export PYTHONPATH="$PWD/src"
.venv/bin/python -m unittest discover -s tests -p test_python.py -v
.venv/bin/python -m unittest discover -s tests -p 'test_advi*.py' -v
.venv/bin/python tests/test_native.py
.venv/bin/python tests/test_overlay.py
