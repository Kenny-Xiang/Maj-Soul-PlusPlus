#!/bin/zsh
set -e
cd "${0:A:h}"
mkdir -p .local
exec </dev/null >>.local/launcher.log 2>&1
if [[ ! -x .venv/bin/python ]]; then
  /usr/bin/python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import WebKit, AppKit'; then
  .venv/bin/python -m pip install --disable-pip-version-check --no-cache-dir --upgrade pip
  .venv/bin/python -m pip install --disable-pip-version-check --no-cache-dir --only-binary=:all: -r requirements.txt
fi
exec .venv/bin/python monitor.py
