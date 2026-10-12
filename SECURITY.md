# Security policy

Report unsafe map scripts, archive-generation vulnerabilities, or other
security issues privately through this repository's GitHub security advisory
form. Do not publish exploit details or secrets in an issue.

Eligible pull request runs review vulnerabilities of all severities and license
findings in runtime, development, and unknown dependency scopes when this
workflow exists on the relevant revision. The workflow has no target-branch
filter. Historical branches without the workflow are not automatically covered;
they remain immutable and are not backport or recreation targets.
Findings and review failures do not block merging. Implementing agents must read
the latest dependency review job summary for the current PR head, even when a bot
comment exists; comments may describe an earlier revision. Fix actionable
introduced findings or record explicit maintainer acceptance of existing risk
before merging; no additional human approval is required. If a review report is absent, vulnerability and
license results are unknown. License metadata reporting does not automate
compatibility decisions; existing repository license policies remain authoritative.

Release tooling is recorded in `package.json` and `package-lock.json`, installed
with `npm ci`, and updated by Dependabot.

GitHub's dependency graph cannot associate advisories with GitHub Actions pinned
to full commit SHAs. Dependency review therefore does not provide advisory
coverage for those action references. Keep the immutable pins and review
Dependabot's action updates and upstream security notices.

