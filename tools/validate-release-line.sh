#!/usr/bin/env bash

set -euo pipefail

repository=$(git rev-parse --show-toplevel)
cd "${repository}"

workspace=$(mktemp -d /tmp/atrinik-content-1x-release.XXXXXX)
trap 'rm -rf -- "${workspace}"' EXIT
first=${workspace}/first
second=${workspace}/second

tools/package-release.sh --version 1.8.2 --revision HEAD "${first}"
tools/package-release.sh --version 1.8.2 --revision HEAD "${second}"
cmp "${first}/atrinik-content-1.8.2.tar.gz" \
  "${second}/atrinik-content-1.8.2.tar.gz"
cmp "${first}/atrinik-content-1.8.2-runtime.tar.gz" \
  "${second}/atrinik-content-1.8.2-runtime.tar.gz"
cmp "${first}/SHA256SUMS" "${second}/SHA256SUMS"
(
  cd "${first}"
  sha256sum --check SHA256SUMS
)

mkdir "${workspace}/runtime"
tar -xzf "${first}/atrinik-content-1.8.2-runtime.tar.gz" \
  -C "${workspace}/runtime"
manifest=${workspace}/runtime/atrinik-content-1.8.2-runtime/manifest.json
jq -e \
  --arg commit "$(git rev-parse HEAD)" \
  '.schema_version == 2 and
    .source.repository == "atrinik/content" and
    .source.branch == "1.x" and
    .source.commit == $commit and
    .release_line == "1.x" and
    .release_version == "1.8.2" and
    .content_format == "classic-ads-v1" and
    .artifact_format == "atrinik-classic-runtime-content-v1" and
    .compatible_classic_releases == ">=1.0.0 <2.0.0" and
    .consumers == ["classic/client", "classic/editor", "classic/server"] and
    .replacement_ready == false and
    .replacement_toolkit_package == false and
    (.license_files | length > 0) and
    (.files | length > 0)' "${manifest}" >/dev/null

if tools/package-release.sh --version 1.8.2 --revision HEAD "${first}" \
  >"${workspace}/no-clobber.stdout" 2>"${workspace}/no-clobber.stderr"; then
  echo "release packaging overwrote an existing output" >&2
  exit 1
fi
grep -Fx "release output already exists: ${first}" \
  "${workspace}/no-clobber.stderr" >/dev/null
