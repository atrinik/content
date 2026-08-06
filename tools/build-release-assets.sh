#!/usr/bin/env bash

set -euo pipefail
if [[ $# -ne 1 || ! $1 =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "usage: $0 MAJOR.MINOR.PATCH" >&2
  exit 2
fi
tools/package-release.sh "v$1" build/release
