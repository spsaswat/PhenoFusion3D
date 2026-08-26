#!/usr/bin/env bash
# Compatibility entry point. The root setup script is the single Linux setup
# path and only creates/populates the project virtual environment.

set -euo pipefail

cd "$(dirname "$0")/.."
exec ./setup.sh "$@"
