"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const {execFileSync} = require("node:child_process");

const VERSION_PATTERN = /^\d+\.\d+\.\d+$/;
const COMMIT_PATTERN = /^[0-9a-f]{40}$/;
const RELEASE_ASSETS = Object.freeze([
  "SHA256SUMS",
  "atrinik-content-${version}.tar.gz",
  "atrinik-content-${version}-runtime.tar.gz",
  "atrinik-content-${version}-classic-runtime.tar.gz",
]);

function fail(message) {
  throw new Error(message);
}

function parseArguments(argv) {
  if (
    argv.length !== 2 ||
    !VERSION_PATTERN.test(argv[0]) ||
    !COMMIT_PATTERN.test(argv[1])
  ) {
    fail("usage: node scripts/release/verify-release.cjs VERSION COMMIT_SHA");
  }
  return {
    version: argv[0],
    tag: `v${argv[0]}`,
    commit: argv[1],
  };
}

function releaseRepository() {
  const repository = process.env.GITHUB_REPOSITORY || "atrinik/content";
  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repository)) {
    fail("GITHUB_REPOSITORY must be an owner/name pair");
  }
  return repository;
}

function runGitHub(args) {
  const command = process.env.ATRINIK_RELEASE_GH || "gh";
  try {
    return execFileSync(command, args, {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    }).trim();
  } catch (error) {
    const detail = error.stderr?.toString().trim() || error.message;
    fail(`gh ${args.join(" ")} failed: ${detail}`);
  }
}

function releaseAssetNames(release) {
  if (!Array.isArray(release.assets)) {
    fail("published release did not return an asset list");
  }
  return new Set(release.assets.map((asset) => asset.name));
}

function expectedAssets(version) {
  return RELEASE_ASSETS.map((asset) => asset.replace("${version}", version));
}

function ensureRegularFile(directory, name) {
  const file = path.join(directory, name);
  let stat;
  try {
    stat = fs.lstatSync(file);
  } catch {
    fail(`published release did not provide ${name}`);
  }
  if (!stat.isFile()) {
    fail(`published release asset is not a regular file: ${name}`);
  }
  return file;
}

function verifyChecksums(directory, archives) {
  const sumsPath = ensureRegularFile(directory, "SHA256SUMS");
  const lines = fs
    .readFileSync(sumsPath, "utf8")
    .split(/\r?\n/)
    .filter((line) => line.length > 0);
  const entries = new Map();
  for (const line of lines) {
    const match = /^([0-9a-f]{64})  (.+)$/.exec(line);
    if (!match || entries.has(match[2])) {
      fail(`invalid or duplicate SHA256SUMS entry: ${line}`);
    }
    entries.set(match[2], match[1]);
  }
  if (entries.size !== archives.length) {
    fail("SHA256SUMS does not contain exactly the published archives");
  }
  for (const archive of archives) {
    const archivePath = ensureRegularFile(directory, archive);
    const expected = entries.get(archive);
    if (!expected) {
      fail(`SHA256SUMS is missing ${archive}`);
    }
    const actual = crypto
      .createHash("sha256")
      .update(fs.readFileSync(archivePath))
      .digest("hex");
    if (actual !== expected) {
      fail(`checksum mismatch for ${archive}`);
    }
  }
}

function verifyRelease(argv) {
  const {version, tag, commit} = parseArguments(argv);
  const repository = releaseRepository();
  const assets = expectedAssets(version);
  const release = JSON.parse(
    runGitHub([
      "release",
      "view",
      tag,
      "--repo",
      repository,
      "--json",
      "isDraft,isPrerelease,tagName,assets,url",
    ]),
  );
  if (release.tagName !== tag) {
    fail(`published release tag mismatch: expected ${tag}`);
  }
  if (release.isDraft || release.isPrerelease) {
    fail(`release ${tag} is not a published stable release`);
  }
  const available = releaseAssetNames(release);
  for (const asset of assets) {
    if (!available.has(asset)) {
      fail(`published release is missing ${asset}`);
    }
  }

  const taggedCommit = runGitHub([
    "api",
    `repos/${repository}/commits/${tag}`,
    "--jq",
    ".sha",
  ]);
  if (taggedCommit !== commit) {
    fail(`release ${tag} points to ${taggedCommit}, expected ${commit}`);
  }

  const downloadDirectory = fs.mkdtempSync(
    path.join(os.tmpdir(), "atrinik-content-release-"),
  );
  try {
    for (const asset of assets) {
      runGitHub([
        "release",
        "download",
        tag,
        "--repo",
        repository,
        "--pattern",
        asset,
        "--dir",
        downloadDirectory,
        "--clobber",
      ]);
    }
    verifyChecksums(
      downloadDirectory,
      assets.filter((asset) => asset !== "SHA256SUMS"),
    );
  } finally {
    fs.rmSync(downloadDirectory, {recursive: true, force: true});
  }

  console.log(
    `verified ${tag} at ${commit} in ${repository}; repeat runs are read-only and idempotent`,
  );
}

if (require.main === module) {
  try {
    verifyRelease(process.argv.slice(2));
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}

module.exports = {
  RELEASE_ASSETS,
  expectedAssets,
  parseArguments,
  verifyChecksums,
  verifyRelease,
};
