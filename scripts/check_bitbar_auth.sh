#!/usr/bin/env bash
# Run from the repository with the Bitbar environment variables already exported.
set -euo pipefail

poetry run python - <<'PY'
import os

from mozilla_bitbar_devicepool import TESTDROID
from testdroid import RequestResponseError

print("Server:", os.environ.get("TESTDROID_URL") or "(missing)")
print("API key set:", bool(os.environ.get("TESTDROID_APIKEY")))

if TESTDROID is None:
    raise SystemExit("Missing TESTDROID_URL or TESTDROID_APIKEY")

failed = False
for path in ("api/v2/me", "api/v2/me/device-groups"):
    try:
        TESTDROID.get(path, payload={"limit": 1})
        print(f"{path}: OK")
    except RequestResponseError as exc:
        print(f"{path}: {exc}")
        failed = True

raise SystemExit(1 if failed else 0)
PY
