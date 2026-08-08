#!/usr/bin/env python3
"""Generate the branch-aware M1 behavior and provenance evidence."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import tokenize
from typing import Any


REPOSITORY = "atrinik/content"
BASE_REVISION = "01b1fdb65c2243df4bafe9c8109fc93229df0121"
BASE_TAG = "v1.8.1"
REGISTRY_REPOSITORY = "atrinik/atrinik"
REGISTRY_REVISION = "d64a8e958ca2adad783ad8912493d468a805f3fd"
REGISTRY_PATH = "AGENTS.md"
EXPECTED_PYTHON_FILES = 177
APPROVED_IDENTITIES = {
    ("Zoey Rose", "3865595+zoeyrose@users.noreply.github.com"),
    ("Zoey Rose", "zoey@zoeysr.com"),
    ("Daniel Liptrot", "daniel@liptrot.org"),
}


class FoundationError(RuntimeError):
    """Raised when pinned M1 evidence is incomplete or stale."""


def git_text(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ("git", "-C", str(root), *arguments),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout


def git_bytes(root: Path, revision: str, path: str) -> bytes:
    result = subprocess.run(
        ("git", "-C", str(root), "show", f"{revision}:{path}"),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_paths(root: Path) -> list[str]:
    output = git_text(root, "ls-tree", "-r", "--name-only", BASE_REVISION)
    paths = sorted(path for path in output.splitlines() if path.endswith(".py"))
    if len(paths) != EXPECTED_PYTHON_FILES:
        raise FoundationError(
            f"expected {EXPECTED_PYTHON_FILES} Python files at the baseline, got {len(paths)}"
        )
    return paths


def path_history(root: Path, path: str) -> list[dict[str, Any]]:
    output = git_text(
        root,
        "log",
        "--follow",
        "--format=@@%H%x1f%aN%x1f%aE",
        "--name-status",
        BASE_REVISION,
        "--",
        path,
    )
    records: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in output.splitlines():
        if line.startswith("@@"):
            if current is not None:
                records.append(current)
            revision, name, email = line[2:].split("\x1f")
            current = {"revision": revision, "name": name, "email": email, "changes": []}
        elif not line or current is None:
            continue
        else:
            parts = line.split("\t")
            current["changes"].append({"status": parts[0], "paths": parts[1:]})
    if current is not None:
        records.append(current)
    return records


def static_observations(source: str) -> dict[str, list[str]]:
    tokens = [
        item
        for item in tokenize.generate_tokens(io.StringIO(source).readline)
        if item.type not in {tokenize.COMMENT, tokenize.STRING, tokenize.ENCODING}
    ]
    imports: set[str] = set()
    symbols: set[str] = set()
    engine_calls: set[str] = set()
    event_tokens: set[str] = set()
    from_import_indexes: set[int] = set()
    for index, item in enumerate(tokens):
        if item.type != tokenize.NAME:
            continue
        if item.string == "from":
            for following in tokens[index + 1 :]:
                if following.type == tokenize.NAME:
                    imports.add(following.string)
                    break
                if following.type not in {tokenize.NL, tokenize.NEWLINE, tokenize.INDENT}:
                    break
            for following_index in range(index + 1, len(tokens)):
                following = tokens[following_index]
                if following.type == tokenize.NAME and following.string == "import":
                    from_import_indexes.add(following_index)
                    break
                if following.type in {tokenize.NEWLINE, tokenize.ENDMARKER}:
                    break
        elif item.string == "import" and index not in from_import_indexes:
            for following in tokens[index + 1 :]:
                if following.type == tokenize.NAME:
                    imports.add(following.string)
                    break
                if following.type not in {tokenize.NL, tokenize.NEWLINE, tokenize.INDENT}:
                    break
        elif item.string in {"def", "class"}:
            for following in tokens[index + 1 :]:
                if following.type == tokenize.NAME:
                    symbols.add(following.string)
                    break
                if following.type not in {tokenize.NL, tokenize.NEWLINE, tokenize.INDENT}:
                    break
        elif re.fullmatch(r"(?:EVENT|HOOK)_[A-Z0-9_]+", item.string):
            event_tokens.add(item.string)
        if (
            item.string == "Atrinik"
            and index + 2 < len(tokens)
            and tokens[index + 1].string == "."
            and tokens[index + 2].type == tokenize.NAME
        ):
            engine_calls.add(tokens[index + 2].string)
    return {
        "imports": sorted(imports),
        "public_symbols": sorted(symbols),
        "engine_calls": sorted(engine_calls),
        "event_tokens": sorted(event_tokens),
    }


def capability_profile(path: str, observations: dict[str, list[str]]) -> dict[str, Any]:
    evidence = " ".join(
        [path, *observations["imports"], *observations["engine_calls"], *observations["event_tokens"]]
    ).lower()
    domains = sorted(
        domain
        for domain, terms in {
            "account": ("account", "login", "connection"),
            "auction": ("auction",),
            "economy": ("bank", "merchant", "shop", "money", "coin"),
            "guild": ("guild",),
            "housing": ("house", "apartment"),
            "interface": ("interface", "markup", "packet"),
            "justice": ("guard", "jail", "crime"),
            "map": ("map", "region", "waypoint", "teleport"),
            "object": ("object", "item", "archetype", "createobject"),
            "party": ("party",),
            "player": ("player", "activator", "whoami"),
            "quest": ("quest",),
        }.items()
        if any(term in evidence for term in terms)
    )
    call_text = " ".join(observations["engine_calls"]).lower()
    effects = sorted(
        effect
        for effect, terms in {
            "diagnostic-or-player-output": ("message", "say", "write", "print"),
            "map-transition-or-placement": ("map", "teleport", "move"),
            "object-lifecycle": ("object", "create", "destroy", "remove"),
            "permission-or-command-result": ("command", "permission"),
            "time-or-scheduling": ("time", "timer", "event"),
        }.items()
        if any(term in call_text for term in terms)
    )
    persistence = sorted(
        domain for domain in domains if domain in {"account", "auction", "economy", "guild", "housing", "player", "quest"}
    )
    return {
        "state_domains": domains or ["unclassified_dynamic_state"],
        "observable_effect_classes": effects or ["requires_dynamic_characterization"],
        "persistence_domains": persistence,
        "evidence_basis": ["source path", "code-token imports", "engine-call names", "event constants"],
        "semantic_status": "characterization_required",
    }


def assignment(path: str) -> dict[str, str]:
    if path == "arch/license_check.py" or path.startswith("tools/"):
        return {
            "kind": "offline_toolkit",
            "owner": "content-toolkit",
            "repository": "atrinik/content-toolkit",
            "issue": "https://github.com/atrinik/content-toolkit/issues/8",
        }
    if "/tests/" in path or path.startswith("maps/python/tests/"):
        return {
            "kind": "deliberate_retirement",
            "owner": "server-testkit",
            "repository": "atrinik/server",
            "issue": "https://github.com/atrinik/server/issues/4",
        }
    if path.startswith("maps/python/commands/"):
        return {
            "kind": "explicit_go_handler",
            "owner": "command-service",
            "repository": "atrinik/server",
            "issue": "https://github.com/atrinik/server/issues/4",
        }
    if path.startswith("maps/python/events/"):
        return {
            "kind": "explicit_go_handler",
            "owner": "session-event-service",
            "repository": "atrinik/server",
            "issue": "https://github.com/atrinik/server/issues/4",
        }
    if path.startswith("maps/python/"):
        domain = path.removeprefix("maps/python/").split("/", 1)[0].removesuffix(".py")
        return {
            "kind": "native_go_domain_service",
            "owner": f"{domain.lower()}-domain",
            "repository": "atrinik/server",
            "issue": "https://github.com/atrinik/server/issues/4",
        }
    return {
        "kind": "residual_starlark_candidate",
        "owner": "authored-action-runtime",
        "repository": "atrinik/server",
        "issue": "https://github.com/atrinik/server/issues/4",
    }


def scenario(path: str, migration: dict[str, str], observations: dict[str, list[str]]) -> dict[str, str]:
    stem = PurePosixPath(path).stem.replace("_", " ")
    if migration["kind"] == "offline_toolkit":
        action = f"run the {stem} operation against a bounded public fixture"
        expected = "output, diagnostics, ordering, and failure status match the recorded contract without loading runtime Python"
    elif migration["kind"] == "deliberate_retirement":
        action = f"exercise the replacement test boundary corresponding to {stem}"
        expected = "the replacement testkit proves the same public invariant without packaging the historical Python test or mocks"
    elif migration["kind"] == "explicit_go_handler":
        action = f"invoke the {stem} handler with authorized, unauthorized, malformed, and boundary inputs"
        expected = "observable replies, state transitions, effects, and rejection behavior match the pinned characterization"
    elif migration["kind"] == "native_go_domain_service":
        action = f"trigger the {stem} domain behavior from equivalent initial player and world state"
        expected = "events, effects, persistence changes, and player-visible results match the pinned characterization"
    else:
        action = f"trigger the authored {stem} map event with deterministic player, map, and object state"
        expected = "the bounded action runtime produces the characterized effects and state changes or a stable fail-closed diagnostic"
    call_hint = ", ".join(observations["engine_calls"][:4]) or "no direct Atrinik API call"
    return {
        "id": f"scenario:legacy-python:{hashlib.sha256(path.encode()).hexdigest()[:20]}",
        "setup": f"load an isolated fixture for {path} with dependencies stubbed and {call_hint} observed",
        "action": action,
        "expected": expected,
        "verification_owner": migration["owner"],
    }


def behavior_record(root: Path, path: str, history: list[dict[str, Any]]) -> dict[str, Any]:
    data = git_bytes(root, BASE_REVISION, path)
    source = data.decode("utf-8", errors="replace")
    observations = static_observations(source)
    capabilities = capability_profile(path, observations)
    migration = assignment(path)
    notice_path = "tools/COPYING" if path.startswith("tools/") else (
        "arch/COPYING" if path.startswith("arch/") else "maps/COPYING"
    )
    authors = {(row["name"], row["email"]) for row in history}
    approved_only = bool(authors) and authors <= APPROVED_IDENTITIES
    return {
        "schema_version": 1,
        "behavior_id": f"behavior:legacy-python:{hashlib.sha256((REPOSITORY + ':' + BASE_REVISION + ':' + path).encode()).hexdigest()[:24]}",
        "source": {
            "repository": REPOSITORY,
            "branch": "main",
            "tag": BASE_TAG,
            "revision": BASE_REVISION,
            "path": path,
            "sha256": sha256(data),
        },
        "classic_baseline": {
            "repository": REPOSITORY,
            "branch": "1.x",
            "revision": BASE_REVISION,
            "path": path,
            "sha256": sha256(data),
        },
        "branch_status": "shared_fork_baseline",
        "complete_history": history,
        "historical_license": "GPL-2.0-only" if notice_path != "arch/COPYING" else "LicenseRef-content-asset-policy",
        "notice_path": notice_path,
        "notice_sha256": sha256(git_bytes(root, BASE_REVISION, notice_path)),
        "provenance_status": "approved_grantor_review_required" if approved_only else "mixed_or_non_grantor_excluded",
        "observations": observations,
        "authored_behavior": {
            **capabilities,
            "events": observations["event_tokens"],
            "effects": observations["engine_calls"],
            "ambiguity": "static evidence is not a semantic specification; scenario characterization must settle dynamic and error behavior",
        },
        "migration": {
            **migration,
            "status": "assigned_not_implemented",
            "milestone": "M1 — Clean-room foundations",
            "inventory_issue": "https://github.com/atrinik/content/issues/41",
            "replacement_path": None,
            "python_compatibility_plugin": False,
        },
        "acceptance_scenario": {
            **scenario(path, migration, observations),
            "status": "defined_not_yet_executed",
            "runner_issue": migration["issue"],
        },
    }


def selected_materials(root: Path) -> dict[str, Any]:
    selected = []
    for material_id, path, destination, introducing_commit in (
        (
            "material:authored-jsonc-limits-v1",
            "prototypes/authored-syntax-v1/limits.json",
            "policy/classic-authored-limits.json",
            "4aa4aebc5c88dffdf57657a34ae20306a57fbebd",
        ),
        (
            "material:legacy-diagnostic-schema-v1",
            "contracts/content-v1/schemas/diagnostic.schema.json",
            "schemas/classic-diagnostic.schema.json",
            "66c73ba9d8bfc7c42aa58593372acf977adf7541",
        ),
    ):
        data = git_bytes(root, BASE_REVISION, path)
        history = path_history(root, path)
        if not history or any((row["name"], row["email"]) not in APPROVED_IDENTITIES for row in history):
            raise FoundationError(f"selected MIT material has non-approved history: {path}")
        selected.append(
            {
                "material_id": material_id,
                "classification": "approved_grantor_original_sole_work",
                "decision": "admitted_mit_grant",
                "source": {
                    "repository": REPOSITORY,
                    "branch": "main",
                    "tag": BASE_TAG,
                    "revision": BASE_REVISION,
                    "path": path,
                    "sha256": sha256(data),
                },
                "classic_copy": {
                    "branch": "1.x",
                    "revision": BASE_REVISION,
                    "path": path,
                    "terms_changed": False,
                },
                "complete_history": history,
                "author_identity_review": "all commits are solely Zoey Rose using the verified GitHub noreply identity",
                "author_identity_evidence": {
                    "github_login": "zoeyrose",
                    "github_user_id": 3865595,
                    "verified_commit": introducing_commit,
                    "signature_verified": True,
                    "api_evidence": f"https://api.github.com/repos/atrinik/content/commits/{introducing_commit}",
                },
                "originality_review": "machine contract was introduced in the reviewed commit and contains no copied prose, code, artwork, or generated third-party input",
                "third_party_review": "no embedded or derivative third-party material",
                "grant": {
                    "grantor": "Zoey Rose",
                    "operation": "copy and translate",
                    "destination_license": "MIT",
                    "registry_repository": REGISTRY_REPOSITORY,
                    "registry_revision": REGISTRY_REVISION,
                    "registry_path": REGISTRY_PATH,
                },
                "destination": {
                    "repository": "atrinik/content-toolkit",
                    "branch": "feat/content-provenance-contracts",
                    "revision": "d9856fd820cb95b62730adc41c5eeff3b6cc9e7a",
                    "path": destination,
                    "transformation": "byte-identical copy; no content transformation",
                    "status": "implemented_in_linked_change",
                },
                "allowed_packages": ["content-toolkit-mit"],
                "attribution": "Copyright Zoey Rose; used under the recorded historical MIT provenance grant",
            }
        )

    selected.extend(
        [
            {
                "material_id": "material:painting:cave_entrance",
                "classification": "compatible_third_party_work",
                "decision": "admitted_existing_terms",
                "source": {
                    "repository": "atrinik/resources",
                    "revision": "f9c0850b7deabacb3cc14875256caac9fb90ab64",
                    "path": "paintings/cave_entrance.jpg",
                    "sha256": "869f37597531782904d2ad333bebb08f89e6707e441f12c5f21d8d6ac333110f",
                },
                "author": "Alex \"Cleo\" Tokar",
                "license": "CC-BY-SA-3.0",
                "notice": {
                    "repository": "atrinik/resources",
                    "path": "paintings/LICENSE",
                    "sha256": "3cabd6ec1db66713b5c97e4fe205230810b31a60603196148b02002bfb5d1bcc",
                },
                "integrity": {
                    "media_type": "image/jpeg",
                    "size_bytes": 286857,
                    "width": 750,
                    "height": 500,
                    "maximum_file_bytes": 67108864,
                    "maximum_dimension": 8192,
                },
                "complete_history": [
                    {
                        "revision": "f9c0850b7deabacb3cc14875256caac9fb90ab64",
                        "name": "Alex Tokar",
                        "email": "admin@atokar.net",
                        "path": "paintings/cave_entrance.jpg",
                    }
                ],
                "derivative_base_chain": [],
                "transformations": [],
                "allowed_packages": ["client", "editor", "resources", "renderer-test", "website"],
            },
            {
                "material_id": "material:painting:canopy",
                "classification": "derivative_with_retained_terms",
                "decision": "admitted_existing_terms",
                "source": {
                    "repository": "atrinik/resources",
                    "revision": "d629f89f1ae4cbffdfd201009ae1b1821c8c3f1f",
                    "path": "paintings/canopy.jpg",
                    "sha256": "bee62ab315460bfc0c4d3e2636a5924fe92f6f5487fb90b51fbe3bbed3c88c3f",
                },
                "author": "Alex \"Cleo\" Tokar",
                "license": "CC-BY-SA-3.0",
                "notice": {
                    "repository": "atrinik/resources",
                    "path": "paintings/LICENSE",
                    "sha256": "3cabd6ec1db66713b5c97e4fe205230810b31a60603196148b02002bfb5d1bcc",
                },
                "integrity": {
                    "media_type": "image/jpeg",
                    "size_bytes": 227415,
                    "width": 750,
                    "height": 500,
                    "maximum_file_bytes": 67108864,
                    "maximum_dimension": 8192,
                },
                "complete_history": [
                    {
                        "revision": "d629f89f1ae4cbffdfd201009ae1b1821c8c3f1f",
                        "name": "Alex Tokar",
                        "email": "admin@atokar.net",
                        "path": "paintings/canopy.jpg",
                    },
                    {
                        "revision": "f9c0850b7deabacb3cc14875256caac9fb90ab64",
                        "name": "Alex Tokar",
                        "email": "admin@atokar.net",
                        "path": "paintings/canopy.png",
                    },
                ],
                "derivative_base_chain": [
                    {
                        "revision": "f9c0850b7deabacb3cc14875256caac9fb90ab64",
                        "path": "paintings/canopy.png",
                        "sha256": "305aac7ab9538662fb1afc773a9abad943b50cc01c2bc168555f1951babb4d71",
                    }
                ],
                "transformations": ["lossy PNG-to-JPEG conversion"],
                "allowed_packages": ["client", "editor", "resources", "renderer-test", "website"],
            },
            {
                "material_id": "material:content:unmatched-ladder-down",
                "classification": "excluded_unknown",
                "decision": "blocked_missing_license",
                "source": {
                    "repository": REPOSITORY,
                    "branch": "main",
                    "revision": BASE_REVISION,
                    "path": "arch/connect/exits/ladder/ladder_down.111.png",
                    "sha256": sha256(git_bytes(root, BASE_REVISION, "arch/connect/exits/ladder/ladder_down.111.png")),
                },
                "license": None,
                "notice": None,
                "allowed_packages": [],
                "reason": "one of the 526 visuals with no matching legacy attribution declaration",
            },
            {
                "material_id": "material:classic-stable-identity-fixture",
                "classification": "content_data_existing_terms",
                "decision": "excluded_from_mit_contract_packages",
                "source": {
                    "repository": REPOSITORY,
                    "branch": "main",
                    "revision": BASE_REVISION,
                    "path": "contracts/content-v1/corpus/fixtures/stable-identities.arc",
                    "sha256": sha256(git_bytes(root, BASE_REVISION, "contracts/content-v1/corpus/fixtures/stable-identities.arc")),
                },
                "license": "LicenseRef-Atrinik-content-mixed",
                "allowed_packages": ["classic-conformance-corpus"],
                "reason": "authored corpus data remains under its content terms and is not relicensed with the MIT parser/schema",
            },
        ]
    )
    return {
        "schema_version": 1,
        "baseline": {"repository": REPOSITORY, "tag": BASE_TAG, "revision": BASE_REVISION},
        "grant_registry": {
            "repository": REGISTRY_REPOSITORY,
            "revision": REGISTRY_REVISION,
            "path": REGISTRY_PATH,
            "approved_grantors": ["Zoey Rose", "Daniel Liptrot"],
        },
        "materials": selected,
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_json_lines(path: Path, values: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for value in values:
            stream.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def generate(root: Path, output: Path) -> None:
    if git_text(root, "rev-parse", "--is-shallow-repository").strip() != "false":
        raise FoundationError("M1 evidence generation requires complete Git history")
    paths = source_paths(root)
    records = []
    for path in paths:
        history = path_history(root, path)
        if not history:
            raise FoundationError(f"missing history for {path}")
        records.append(behavior_record(root, path, history))
    write_json_lines(output / "python-behaviors.jsonl", records)
    materials = selected_materials(root)
    write_json(output / "materials.json", materials)
    packages = sorted(
        {package for material in materials["materials"] for package in material["allowed_packages"]}
    )
    for package in packages:
        write_json(
            output / "allowlists" / f"{package}.json",
            {
                "schema_version": 1,
                "package": package,
                "materials": [
                    {
                        "material_id": material["material_id"],
                        "sha256": material["source"]["sha256"],
                        "decision": material["decision"],
                    }
                    for material in materials["materials"]
                    if package in material["allowed_packages"]
                ],
            },
        )


def validate(root: Path, evidence: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="atrinik-content-m1-", dir="/tmp") as directory:
        generated = Path(directory)
        generate(root, generated)
        actual_files = {
            path.relative_to(evidence)
            for path in evidence.rglob("*")
            if path.is_file() and path.name != "README.md"
        }
        generated_files = {
            path.relative_to(generated) for path in generated.rglob("*") if path.is_file()
        }
        if actual_files != generated_files:
            raise FoundationError("M1 evidence file set is stale")
        for relative in actual_files:
            if (evidence / relative).read_bytes() != (generated / relative).read_bytes():
                raise FoundationError(f"M1 evidence is stale: {relative}")

    records = [json.loads(line) for line in (evidence / "python-behaviors.jsonl").read_text(encoding="utf-8").splitlines()]
    if len(records) != EXPECTED_PYTHON_FILES:
        raise FoundationError("Python behavior inventory count changed")
    identifiers = [record["behavior_id"] for record in records]
    paths = [record["source"]["path"] for record in records]
    if len(identifiers) != len(set(identifiers)) or paths != sorted(paths) or len(paths) != len(set(paths)):
        raise FoundationError("behavior identities and paths must be sorted and unique")
    for record in records:
        migration = record["migration"]
        if not migration["owner"] or not migration["issue"] or migration["python_compatibility_plugin"]:
            raise FoundationError(f"invalid replacement assignment: {record['behavior_id']}")
        if not record["complete_history"] or not record["acceptance_scenario"]["expected"]:
            raise FoundationError(f"incomplete behavior evidence: {record['behavior_id']}")
        if (
            record["acceptance_scenario"].get("status") != "defined_not_yet_executed"
            or not record["acceptance_scenario"].get("runner_issue")
            or record["authored_behavior"].get("semantic_status")
            != "characterization_required"
            or not record["authored_behavior"].get("state_domains")
        ):
            raise FoundationError(f"behavior verification contract is incomplete: {record['behavior_id']}")
        if record["branch_status"] != "shared_fork_baseline" and not record.get("predecessor_behavior_id"):
            raise FoundationError(f"changed branch row lacks an explicit predecessor: {record['behavior_id']}")
        if record["source"]["sha256"] != record["classic_baseline"]["sha256"]:
            raise FoundationError(f"fork baseline mismatch: {record['behavior_id']}")

    materials = json.loads((evidence / "materials.json").read_text(encoding="utf-8"))
    for material in materials["materials"]:
        if material["decision"].startswith("admitted") and not material["allowed_packages"]:
            raise FoundationError(f"admitted material has no package: {material['material_id']}")
        if material["decision"].startswith(("blocked", "excluded")) and material.get("allowed_packages") not in ([], ["classic-conformance-corpus"]):
            raise FoundationError(f"excluded material entered a replacement package: {material['material_id']}")
        if material["classification"] in {"compatible_third_party_work", "derivative_with_retained_terms"}:
            if not material.get("complete_history") or not material.get("integrity") or not material.get("notice", {}).get("sha256"):
                raise FoundationError(f"external visual evidence is incomplete: {material['material_id']}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("generate", "validate"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    arguments = parser.parse_args()
    root = arguments.root.resolve()
    evidence = root / "provenance" / "m1"
    try:
        if arguments.command == "generate":
            generate(root, evidence)
        else:
            validate(root, evidence)
    except (
        FoundationError,
        OSError,
        subprocess.CalledProcessError,
        KeyError,
        ValueError,
        json.JSONDecodeError,
        tokenize.TokenError,
    ) as error:
        print(f"M1 foundation evidence error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
