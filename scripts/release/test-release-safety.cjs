"use strict";

const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const {execFileSync} = require("node:child_process");

const ROOT = path.resolve(__dirname, "../..");
const verifierPath = path.join(__dirname, "verify-release.cjs");
const {expectedAssets} = require(verifierPath);

function pluginOptions(config, name) {
  const plugin = config.plugins.find((entry) => entry[0] === name);
  assert.ok(plugin, `missing ${name} plugin`);
  return plugin[1];
}

const releaseConfig = JSON.parse(
  fs.readFileSync(path.join(ROOT, ".releaserc.json"), "utf8"),
);
const execOptions = pluginOptions(releaseConfig, "@semantic-release/exec");
const githubOptions = pluginOptions(releaseConfig, "@semantic-release/github");
assert.equal(githubOptions.successCommentCondition, false);
assert.equal(
  execOptions.successCmd,
  "node scripts/release/verify-release.cjs ${nextRelease.version} ${nextRelease.gitHead}",
);

const fixture = fs.readFileSync(
  path.join(__dirname, "fixtures", "unavailable-local-issues.md"),
  "utf8",
);
for (const reference of ["#308", "#287", "atrinik/atrinik#266"]) {
  assert.ok(fixture.includes(reference), `fixture is missing ${reference}`);
}
assert.match(fixture, /https:\/\/github\.com\/atrinik\/atrinik\/issues\/266/);

const version = "1.2.3";
const commit = "0123456789abcdef0123456789abcdef01234567";
const assets = expectedAssets(version);
const temporary = fs.mkdtempSync(
  path.join(os.tmpdir(), "atrinik-release-safety-test-"),
);
const assetDirectory = path.join(temporary, "assets");
fs.mkdirSync(assetDirectory);
const statePath = path.join(temporary, "gh-state.json");
const fakeGhPath = path.join(temporary, "gh");

try {
  const archiveAssets = assets.filter((asset) => asset !== "SHA256SUMS");
  for (const asset of archiveAssets) {
    fs.writeFileSync(path.join(assetDirectory, asset), `fixture:${asset}\n`);
  }
  const checksums = archiveAssets
    .map((asset) => {
      const digest = crypto
        .createHash("sha256")
        .update(fs.readFileSync(path.join(assetDirectory, asset)))
        .digest("hex");
      return `${digest}  ${asset}`;
    })
    .join("\n");
  fs.writeFileSync(path.join(assetDirectory, "SHA256SUMS"), `${checksums}\n`);

  fs.writeFileSync(
    fakeGhPath,
    `#!/usr/bin/env node
"use strict";
const fs = require("node:fs");
const path = require("node:path");
const args = process.argv.slice(2);
const statePath = process.env.FAKE_GH_STATE;
const state = fs.existsSync(statePath)
  ? JSON.parse(fs.readFileSync(statePath, "utf8"))
  : {view: 0, api: 0, downloads: [], mutations: []};
const save = () => fs.writeFileSync(statePath, JSON.stringify(state));
if (args[0] === "release" && args[1] === "view") {
  state.view += 1;
  save();
  process.stdout.write(JSON.stringify({
    tagName: "v1.2.3",
    isDraft: false,
    isPrerelease: false,
    url: "https://github.com/atrinik/content/releases/tag/v1.2.3",
    assets: JSON.parse(process.env.FAKE_GH_ASSETS).map((name) => ({name})),
  }));
  process.exit(0);
}
if (args[0] === "api") {
  state.api += 1;
  save();
  process.stdout.write(process.env.FAKE_GH_COMMIT + "\\n");
  process.exit(0);
}
if (args[0] === "release" && args[1] === "download") {
  const pattern = args[args.indexOf("--pattern") + 1];
  const directory = args[args.indexOf("--dir") + 1];
  fs.copyFileSync(
    path.join(process.env.FAKE_GH_ASSET_DIR, pattern),
    path.join(directory, pattern),
  );
  state.downloads.push(pattern);
  save();
  process.exit(0);
}
state.mutations.push(args);
save();
process.exit(1);
`,
  );
  fs.chmodSync(fakeGhPath, 0o755);

  const environment = {
    ...process.env,
    ATRINIK_RELEASE_GH: fakeGhPath,
    FAKE_GH_ASSET_DIR: assetDirectory,
    FAKE_GH_ASSETS: JSON.stringify(assets),
    FAKE_GH_COMMIT: commit,
    FAKE_GH_STATE: statePath,
    GITHUB_REPOSITORY: "atrinik/content",
  };
  const run = () =>
    execFileSync(process.execPath, [verifierPath, version, commit], {
      cwd: ROOT,
      env: environment,
      encoding: "utf8",
    });
  assert.match(run(), /verified v1\.2\.3/);
  assert.match(run(), /repeat runs are read-only and idempotent/);

  const state = JSON.parse(fs.readFileSync(statePath, "utf8"));
  assert.equal(state.view, 2);
  assert.equal(state.api, 2);
  assert.deepEqual(state.downloads, assets.concat(assets));
  assert.deepEqual(state.mutations, []);
} finally {
  fs.rmSync(temporary, {recursive: true, force: true});
}

console.log("release safety: unresolved notes, publication coordinates, assets, and idempotent verification validated");
