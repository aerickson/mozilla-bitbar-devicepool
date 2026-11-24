#!/bin/bash

# Creates a nested JSON artifact to verify HyperExecute artifact uploads.
set -euo pipefail

mkdir -p fleetbench-artifacts/nested
printf '{"artifact_glob_smoke": true}\n' >fleetbench-artifacts/nested/result.json
printf 'artifact glob smoke passed\n'
