#!/usr/bin/env bash
# Linux/macOS: start the Nixin brain.
cd "$(dirname "$0")/../brain" && exec .venv/bin/nixin run "$@"
