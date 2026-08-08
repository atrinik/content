#!/usr/bin/env bash

set -euo pipefail

if [[ $# -eq 2 ]]; then
  revision=$1
  output_directory=$2
  if [[ ! ${revision} =~ ^v([0-9]+\.[0-9]+\.[0-9]+)$ ]]; then
    echo "invalid release tag: ${revision}" >&2
    exit 1
  fi
  version=${BASH_REMATCH[1]}
elif [[ $# -eq 5 && $1 == --version && $3 == --revision ]]; then
  version=$2
  revision=$4
  output_directory=$5
  if [[ ! ${version} =~ ^1\.[0-9]+\.[0-9]+$ ]]; then
    echo "classic maintenance version must satisfy 1.x: ${version}" >&2
    exit 1
  fi
else
  echo "usage: $0 TAG OUTPUT_DIRECTORY" >&2
  echo "       $0 --version 1.MINOR.PATCH --revision COMMIT OUTPUT_DIRECTORY" >&2
  exit 2
fi

source_commit=$(git rev-parse "${revision}^{commit}")
source_epoch=$(git show -s --format=%ct "${revision}^{commit}")
package=atrinik-content-${version}
if [[ -e ${output_directory} ]]; then
  echo "release output already exists: ${output_directory}" >&2
  exit 1
fi
mkdir -p "${output_directory}"

git archive --format=tar.gz --prefix="${package}/" \
  --output="${output_directory}/${package}.tar.gz" "${revision}"

runtime_directory=$(mktemp -d)
trap 'rm -rf -- "${runtime_directory}"' EXIT
python3 tools/build_runtime.py --output "${runtime_directory}/${package}-runtime" \
  --source-commit "${source_commit}" --source-branch 1.x
tar --sort=name --mtime="@${source_epoch}" --owner=0 --group=0 --numeric-owner \
  -czf "${output_directory}/${package}-runtime.tar.gz" \
  -C "${runtime_directory}" "${package}-runtime"

(
  cd "${output_directory}"
  sha256sum "${package}.tar.gz" "${package}-runtime.tar.gz" >SHA256SUMS
)
