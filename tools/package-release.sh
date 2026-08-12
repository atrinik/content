#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 TAG OUTPUT_DIRECTORY" >&2
  exit 2
fi

tag=$1
output_directory=$2
if [[ ! ${tag} =~ ^v([0-9]+\.[0-9]+\.[0-9]+)$ ]]; then
  echo "invalid release tag: ${tag}" >&2
  exit 1
fi

version=${BASH_REMATCH[1]}
source_commit=$(git rev-parse "${tag}^{commit}")
source_epoch=$(git show -s --format=%ct "${tag}^{commit}")
package=atrinik-content-${version}
mkdir -p "${output_directory}"

if ! git merge-base --is-ancestor "${source_commit}" refs/heads/main; then
  echo "release tag is not reachable from refs/heads/main: ${tag}" >&2
  exit 1
fi

git archive --format=tar.gz --prefix="${package}/" \
  --output="${output_directory}/${package}.tar.gz" "${tag}"

runtime_directory=$(mktemp -d)
trap 'rm -rf -- "${runtime_directory}"' EXIT
python3 tools/build_runtime.py --output "${runtime_directory}/${package}-runtime" \
  --source-commit "${source_commit}"
python3 tools/build_runtime.py --target classic \
  --output "${runtime_directory}/${package}-classic-runtime" \
  --source-commit "${source_commit}" --release-version "${version}"
tar --sort=name --mtime="@${source_epoch}" --owner=0 --group=0 --numeric-owner \
  -czf "${output_directory}/${package}-runtime.tar.gz" \
  -C "${runtime_directory}" "${package}-runtime"
tar --sort=name --mtime="@${source_epoch}" --owner=0 --group=0 --numeric-owner \
  -czf "${output_directory}/${package}-classic-runtime.tar.gz" \
  -C "${runtime_directory}" "${package}-classic-runtime"

(
  cd "${output_directory}"
  sha256sum "${package}.tar.gz" "${package}-runtime.tar.gz" \
    "${package}-classic-runtime.tar.gz" >SHA256SUMS
)
