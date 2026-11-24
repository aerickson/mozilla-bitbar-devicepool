#!/usr/bin/env bash

set -e

uv run lt_pool_status --pool a55-perf "$@"
