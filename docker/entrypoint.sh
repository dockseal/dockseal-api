#!/bin/sh
set -eu
cd /app
uv sync --frozen
exec "$@"
