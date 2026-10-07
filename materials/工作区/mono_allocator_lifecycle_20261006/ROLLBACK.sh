#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
python_bin="${PYTHON_BIN:?Set PYTHON_BIN to the verified Python executable}"
export PYTHONDONTWRITEBYTECODE=1
"$python_bin" rollback.py
"$python_bin" validate.py ROLLBACK
