# Security policy

Report unsafe map scripts, archive-generation vulnerabilities, or other
security issues privately through this repository's GitHub security advisory
form. Do not publish exploit details or secrets in an issue.

Pull requests run dependency review and reject newly introduced high or critical
advisories in runtime, development, and unknown dependency scopes. Release tooling
is recorded in `package.json` and `package-lock.json`, installed with `npm ci`,
and updated by Dependabot.

GitHub's dependency graph cannot associate advisories with GitHub Actions pinned
to full commit SHAs. Dependency review therefore does not provide advisory
coverage for those action references. Keep the immutable pins and review
Dependabot's action updates and upstream security notices.

