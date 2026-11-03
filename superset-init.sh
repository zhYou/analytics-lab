#!/bin/bash
set -euo pipefail
superset db upgrade
superset init
python /app/pythonpath/bootstrap_superset.py
