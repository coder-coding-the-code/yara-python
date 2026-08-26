#!/usr/bin/env bash
#
# Cloud Agent bootstrap for the yara-python repository.
#
# Prepares two development surfaces:
#   1. yara-python  - the Python interface to YARA (C extension, statically
#                     links the bundled libyara sources from the git submodule).
#   2. ecs-trust-graph - the ECS Guardian Trust FastAPI control plane.
#
# The script is idempotent: it can run repeatedly against a warm or partially
# prepared checkout.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> Installing system packages (build toolchain + OpenSSL headers)"
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -qq
sudo apt-get install -y -qq \
  build-essential \
  python3-dev \
  python3-venv \
  libssl-dev

echo "==> Fetching bundled libyara sources (git submodule)"
git submodule update --init --recursive

echo "==> Creating Python virtual environment (.venv)"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel

echo "==> Installing ECS Guardian Trust dependencies"
pip install -r ecs-trust-graph/requirements.txt

echo "==> Building & installing the yara-python C extension"
pip install .

echo "==> Smoke check: import yara and ecs_trust"
python - <<'PY'
import yara
r = yara.compile(source='rule foo { strings: $a = "lmn" condition: $a }')
assert r.match(data="abclmn"), "yara match failed"
import sys
sys.path.insert(0, "ecs-trust-graph")
from ecs_trust.seed import build_demo
build_demo()
print("yara-python and ecs_trust import OK")
PY

echo "install.sh complete"
