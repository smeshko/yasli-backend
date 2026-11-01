#!/usr/bin/env bash
# Prepares a fresh worktree: the dependencies CI installs.
set -euo pipefail
uv sync --extra dev
