# Security policy

Report unsafe map scripts, archive-generation vulnerabilities, or other
security issues privately through this repository's GitHub security advisory
form. Do not publish exploit details or secrets in an issue.

Pull requests targeting any branch run advisory dependency review for vulnerabilities of all severities
and license findings in runtime, development, and unknown dependency scopes.
Findings and review failures do not block merging. Implementing agents must read
the PR comment or job summary and fix actionable introduced findings or record
explicit maintainer acceptance of existing risk before merging; no additional
human approval is required. If a review report is absent, vulnerability and
license results are unknown.

Release tooling is recorded in `package.json` and `package-lock.json`, installed
with `npm ci`, and updated by Dependabot.

GitHub's dependency graph cannot associate advisories with GitHub Actions pinned
to full commit SHAs. Dependency review therefore does not provide advisory
coverage for those action references. Keep the immutable pins and review
Dependabot's action updates and upstream security notices.

