"""Reproducible Linux baseline measurements for the authored-syntax decision."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any, Sequence

from tools.content_contracts.contracts import load_json
from tools.content_contracts.corpus import inspect_document

from . import jsonc, yaml12
from .evaluation import validate_baseline_lock
from .limits import PrototypeError
from .model import from_legacy, validate as validate_model


ROOT = Path(__file__).parents[2].resolve()
SERVER_PREFIX = "ATRINIK_CONTENT_BENCHMARK\t"
CHECKER_BOOTSTRAP = (
    "import builtins,runpy,sys;"
    "builtins.xrange=range;"
    "from configparser import ConfigParser;"
    "ConfigParser.readfp=ConfigParser.read_file;"
    "script=sys.argv[1];sys.argv=sys.argv[1:];"
    "runpy.run_path(script,run_name='__main__')"
)
CODECS = {"jsonc": jsonc, "yaml12": yaml12}


def _run(
    arguments: Sequence[str],
    *,
    cwd: Path,
    timeout: int,
    stdout: int | None = subprocess.PIPE,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(arguments),
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=stdout,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or "").strip()
        raise PrototypeError(
            "command failed ({}): {}{}".format(
                result.returncode,
                " ".join(arguments),
                ": " + detail[-2000:] if detail else "",
            )
        )
    return result


def _git_commit(path: Path) -> str:
    result = _run(("git", "rev-parse", "HEAD"), cwd=path, timeout=10)
    commit = result.stdout.strip()
    if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit):
        raise PrototypeError("repository has no canonical commit: {}".format(path))
    return commit


def _git_is_clean(path: Path) -> bool:
    result = _run(
        ("git", "status", "--porcelain", "--untracked-files=normal"),
        cwd=path,
        timeout=30,
    )
    return not result.stdout.strip()


def _git_paths_are_clean(path: Path, paths: Sequence[str]) -> bool:
    result = _run(
        (
            "git",
            "status",
            "--porcelain",
            "--untracked-files=normal",
            "--",
            *paths,
        ),
        cwd=path,
        timeout=30,
    )
    return not result.stdout.strip()


def _paths_digest(root: Path, paths: Sequence[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        if path.is_symlink() or not path.is_file():
            raise PrototypeError("digest input is missing or unsafe: {}".format(path))
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def _summary(values: Sequence[int]) -> dict[str, Any]:
    if not values:
        raise PrototypeError("cannot summarize an empty measurement")
    ordered = sorted(values)
    p95 = ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]
    return {
        "samples": len(ordered),
        "min": ordered[0],
        "median": statistics.median(ordered),
        "p95": p95,
        "max": ordered[-1],
        "raw": list(values),
    }


def _map_candidates(root: Path) -> list[tuple[int, str, Path]]:
    candidates = []
    maps_root = root / "maps"
    for path in maps_root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open("rb") as handle:
            if handle.read(9) != b"arch map\n":
                continue
        relative = path.relative_to(maps_root).as_posix()
        candidates.append((path.stat().st_size, relative, path))
    if len(candidates) < 4:
        raise PrototypeError("not enough authored maps for representative selection")
    return sorted(candidates)


def select_representative_maps(root: Path) -> list[dict[str, Any]]:
    candidates = _map_candidates(root)
    quantiles = (("p10", 1, 10), ("p50", 1, 2), ("p90", 9, 10), ("max", 1, 1))
    grammar = load_json(root / "contracts/content-v1/grammar-inventory.json")
    selected = []
    seen = set()
    for label, numerator, denominator in quantiles:
        index = ((len(candidates) - 1) * numerator + denominator // 2) // denominator
        size, relative, path = candidates[index]
        if relative in seen:
            raise PrototypeError("representative quantiles selected the same map")
        seen.add(relative)
        raw = path.read_bytes()
        inspection, summary = inspect_document(
            path,
            "map",
            grammar,
            display_path="maps/" + relative,
            source_bytes=raw,
        )
        if not summary["accepted"]:
            raise PrototypeError(
                "representative map is outside the fixed grammar: {}".format(relative)
            )
        header_fields = {
            field["name"]: field["value"]
            for node in inspection["nodes"]
            if node["kind"] == "map-header"
            for field in node["fields"]
        }
        if header_fields.get("no_save", "0") not in ("", "0"):
            raise PrototypeError("representative map cannot exercise swap: {}".format(relative))
        selected.append(
            {
                "size_class": label,
                "corpus_index": index,
                "corpus_count": len(candidates),
                "path": "maps/" + relative,
                "logical_id": "/" + relative,
                "bytes": size,
                "objects": summary["objects"],
                "comments": summary["comments"],
                "source_sha256": hashlib.sha256(raw).hexdigest(),
                "_path": path,
                "_comment_lines": inspection["comments"],
            }
        )
    return selected


def _prototype_measurements(
    maps: list[dict[str, Any]], iterations: int
) -> dict[str, Any]:
    reports = []
    for entry in maps:
        raw = entry["_path"].read_bytes()
        model = from_legacy(
            raw,
            "map",
            entry["logical_id"],
            entry["_comment_lines"],
        )
        formats = {}
        for name, codec in CODECS.items():
            encoded = codec.encode(model)
            encode_ns = []
            decode_ns = []
            validate_ns = []
            for _ in range(iterations):
                started = time.perf_counter_ns()
                candidate = codec.encode(model)
                encode_ns.append(time.perf_counter_ns() - started)
                if candidate != encoded:
                    raise PrototypeError("prototype formatter became nondeterministic")
                started = time.perf_counter_ns()
                decoded = codec.decode(candidate)
                decode_ns.append(time.perf_counter_ns() - started)
                started = time.perf_counter_ns()
                reconstructed = validate_model(decoded)
                validate_ns.append(time.perf_counter_ns() - started)
                if reconstructed != raw:
                    raise PrototypeError("prototype benchmark lost source bytes")
            formats[name] = {
                "encoded_bytes": len(encoded.encode("utf-8")),
                "expansion_ratio": round(len(encoded.encode("utf-8")) / len(raw), 6),
                "encode_ns": _summary(encode_ns),
                "decode_ns": _summary(decode_ns),
                "model_validation_ns": _summary(validate_ns),
            }
        reports.append(
            {
                "size_class": entry["size_class"],
                "logical_id": entry["logical_id"],
                "legacy_bytes": len(raw),
                "formats": formats,
            }
        )
    return {"iterations_per_map": iterations, "maps": reports}


def _collection_and_checker_measurements(
    root: Path,
    tools_root: Path,
    maps: list[dict[str, Any]],
    collection_iterations: int,
    checker_iterations: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    checker = tools_root / "map-checker/map-checker.py"
    if checker.is_symlink() or not checker.is_file():
        raise PrototypeError("classic checker entry point is missing or unsafe")
    build_root = _safe_build_root(root)
    collection_ms = []
    checker_reports = []

    with tempfile.TemporaryDirectory(prefix="syntax-benchmark-", dir=build_root) as temporary:
        temporary_root = Path(temporary)
        runtime = temporary_root / "runtime-final"
        for sample in range(collection_iterations):
            output = (
                runtime
                if sample == collection_iterations - 1
                else temporary_root / "runtime-{}".format(sample)
            )
            started = time.perf_counter_ns()
            _run(
                (sys.executable, str(root / "tools/build_runtime.py"), "--output", str(output)),
                cwd=root,
                timeout=300,
            )
            collection_ms.append((time.perf_counter_ns() - started) // 1_000_000)

        for entry in maps:
            samples = []
            map_path = runtime / entry["path"]
            arguments = (
                sys.executable,
                "-c",
                CHECKER_BOOTSTRAP,
                str(checker),
                "--cli",
                "--text-only",
                "--directory={}".format(runtime / "maps"),
                "--arch={}".format(runtime / "lib"),
                "--regions={}".format(runtime / "maps/regions.reg"),
                "--map={}".format(map_path),
            )
            for _ in range(checker_iterations):
                started = time.perf_counter_ns()
                _run(
                    arguments,
                    cwd=checker.parent,
                    timeout=120,
                    stdout=subprocess.DEVNULL,
                )
                samples.append((time.perf_counter_ns() - started) // 1_000_000)
            checker_reports.append(
                {
                    "size_class": entry["size_class"],
                    "logical_id": entry["logical_id"],
                    "wall_ms": _summary(samples),
                }
            )

    return (
        {
            "iterations": collection_iterations,
            "wall_ms": _summary(collection_ms),
            "cache_policy": (
                "new destination each run; sample 0 starts before intentional warming and "
                "later samples use ordinary OS cache state"
            ),
        },
        {
            "implementation": "classic map checker",
            "repository_commit": _git_commit(tools_root),
            "iterations_per_map": checker_iterations,
            "python_compatibility_shim": [
                "ConfigParser.readfp=ConfigParser.read_file",
                "builtins.xrange=range",
            ],
            "maps": checker_reports,
        },
    )


def _parse_server_output(output: str, expected_maps: set[str]) -> dict[str, Any]:
    headers: dict[str, str] = {}
    samples = []
    for line in output.splitlines():
        if not line.startswith(SERVER_PREFIX):
            continue
        fields = line.split("\t")
        if len(fields) == 3:
            _, key, value = fields
            if key in headers:
                raise PrototypeError("duplicate server benchmark header: {}".format(key))
            headers[key] = value
        elif len(fields) == 8 and fields[1] == "map":
            _, _, logical_id, sample, cold, warm, swap, reload = fields
            if logical_id not in expected_maps:
                raise PrototypeError("unexpected server benchmark map")
            samples.append(
                {
                    "logical_id": logical_id,
                    "sample": _nonnegative_decimal(sample, "server sample index"),
                    "cold_original_us": _nonnegative_decimal(cold, "server cold timing"),
                    "warm_lookup_us": _nonnegative_decimal(warm, "server warm timing"),
                    "swap_us": _nonnegative_decimal(swap, "server swap timing"),
                    "temporary_reload_us": _nonnegative_decimal(
                        reload, "server reload timing"
                    ),
                }
            )
        else:
            raise PrototypeError("malformed server benchmark record")
    required = {
        "format",
        "mode",
        "iterations",
        "startup_us",
        "archetype_init_us",
        "startup_peak_rss_kib",
    }
    if (
        set(headers) != required
        or headers["format"] != "1"
        or headers["mode"] != "offline-authored-content"
    ):
        raise PrototypeError("server benchmark header is incomplete")
    iterations = _nonnegative_decimal(headers["iterations"], "server iteration count")
    if iterations < 1 or iterations > 100 or not expected_maps:
        raise PrototypeError("server benchmark iteration or map population is invalid")
    sample_keys = {(sample["logical_id"], sample["sample"]) for sample in samples}
    expected_keys = {
        (logical_id, sample)
        for logical_id in expected_maps
        for sample in range(iterations)
    }
    if sample_keys != expected_keys or len(sample_keys) != len(samples):
        raise PrototypeError("server benchmark sample identities are incomplete or duplicated")
    return {"headers": headers, "samples": samples}


def _nonnegative_decimal(value: str, description: str) -> int:
    if not value or len(value) > 20 or not value.isascii() or not value.isdigit():
        raise PrototypeError("{} is not a bounded nonnegative integer".format(description))
    return int(value)


def _server_measurements(
    workspace_root: Path,
    profile: str,
    state: str,
    maps: list[dict[str, Any]],
    runs: int,
    iterations: int,
) -> dict[str, Any]:
    wrapper = workspace_root / "atrinik"
    if wrapper.is_symlink() or not wrapper.is_file():
        raise PrototypeError("Atrinik workspace wrapper is missing or unsafe")
    logical_ids = [entry["logical_id"] for entry in maps]
    expected = set(logical_ids)
    startup_us = []
    archetype_us = []
    rss_kib = []
    by_map = {
        logical_id: {
            "cold_original_us": [],
            "warm_lookup_us": [],
            "swap_us": [],
            "temporary_reload_us": [],
        }
        for logical_id in logical_ids
    }

    for run in range(runs):
        result = _run(
            (
                str(wrapper),
                "run",
                "server",
                "--profile",
                profile,
                "--state",
                state,
                "--",
                "--content_benchmark={}".format(",".join(logical_ids)),
                "--content_benchmark_iterations={}".format(iterations),
            ),
            cwd=workspace_root,
            timeout=600,
        )
        parsed = _parse_server_output(result.stdout, expected)
        headers = parsed["headers"]
        if _nonnegative_decimal(headers["iterations"], "server iteration count") != iterations:
            raise PrototypeError("server benchmark used an unexpected iteration count")
        startup_us.append(_nonnegative_decimal(headers["startup_us"], "server startup timing"))
        archetype_us.append(
            _nonnegative_decimal(headers["archetype_init_us"], "server archetype timing")
        )
        rss_kib.append(
            _nonnegative_decimal(headers["startup_peak_rss_kib"], "server peak RSS")
        )
        for sample in parsed["samples"]:
            for metric in by_map[sample["logical_id"]]:
                value = sample[metric]
                if value < 0:
                    raise PrototypeError("server benchmark timing must not be negative")
                by_map[sample["logical_id"]][metric].append(value)

    reports = []
    for entry in maps:
        metrics = by_map[entry["logical_id"]]
        reports.append(
            {
                "size_class": entry["size_class"],
                "logical_id": entry["logical_id"],
                **{metric: _summary(values) for metric, values in metrics.items()},
            }
        )
    return {
        "mode": "offline-authored-content",
        "profile": profile,
        "state": state,
        "process_runs": runs,
        "iterations_per_map_per_run": iterations,
        "startup_us": _summary(startup_us),
        "archetype_init_us": _summary(archetype_us),
        "startup_peak_rss_kib": _summary(rss_kib),
        "maps": reports,
    }


def _topology_input_components(topology: Any) -> dict[str, Any]:
    components = topology.get("components")
    dependencies = topology.get("dependencies")
    providers = topology.get("providers", {})
    if (
        not isinstance(components, dict)
        or not isinstance(dependencies, list)
        or not dependencies
        or not isinstance(providers, dict)
        or any(not isinstance(name, str) for name in dependencies)
        or "server" not in dependencies
        or "content" not in dependencies
    ):
        raise PrototypeError("wrapper topology is missing server/content inputs")
    resolved = {
        name: providers.get(name, name)
        for name in dependencies
    }
    if any(
        not isinstance(component, str) or component not in components
        for component in resolved.values()
    ):
        raise PrototypeError("wrapper topology is missing server/content inputs")
    inputs = {
        name: {
            "commit": components[resolved[name]]["head"],
            "dirty": components[resolved[name]]["dirty"],
            "path": components[resolved[name]]["path"],
        }
        for name in sorted(dependencies)
    }
    dirty = [name for name, value in inputs.items() if value["dirty"]]
    if dirty:
        raise PrototypeError("benchmark topology inputs must be clean: {}".format(", ".join(dirty)))
    return inputs


def _topology_inputs(workspace_root: Path, profile: str) -> dict[str, Any]:
    result = _run(
        (
            str(workspace_root / "atrinik"),
            "topology",
            "show",
            profile,
            "--service",
            "server",
            "--json",
        ),
        cwd=workspace_root,
        timeout=30,
    )
    try:
        topology = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise PrototypeError("wrapper topology output is not JSON") from error
    return _topology_input_components(topology)


def _implementation_digest(root: Path) -> str:
    paths = sorted((root / "tools/syntax_evaluation").glob("*.py"))
    paths.append(root / "prototypes/authored-syntax-v1/limits.json")
    return _paths_digest(root, paths)


def _workspace_runner_digest(workspace_root: Path) -> str:
    return _paths_digest(
        workspace_root,
        [workspace_root / "atrinik", *(workspace_root / "atrinik_workspace").glob("*.py")],
    )


def benchmark(
    root: Path,
    workspace_root: Path,
    tools_root: Path,
    *,
    profile: str,
    state: str,
    prototype_iterations: int,
    collection_iterations: int,
    checker_iterations: int,
    server_runs: int,
    server_iterations: int,
) -> dict[str, Any]:
    root = root.resolve(strict=True)
    workspace_root = workspace_root.resolve(strict=True)
    tools_root = tools_root.resolve(strict=True)
    if platform.system() != "Linux":
        raise PrototypeError("reproducible authored-syntax baseline measurements require Linux")
    if not _git_is_clean(tools_root):
        raise PrototypeError("classic tools input must be a clean worktree")
    if not _git_paths_are_clean(workspace_root, ("atrinik", "atrinik_workspace")):
        raise PrototypeError("Atrinik workspace runner input must be clean")
    lock = validate_baseline_lock(root)
    topology_inputs = _topology_inputs(workspace_root, profile)
    if Path(topology_inputs["content"]["path"]).resolve() != root:
        raise PrototypeError("profile content selector does not match --root")
    maps = select_representative_maps(root)
    prototype = _prototype_measurements(maps, prototype_iterations)
    collection, checker = _collection_and_checker_measurements(
        root,
        tools_root,
        maps,
        collection_iterations,
        checker_iterations,
    )
    server = _server_measurements(
        workspace_root,
        profile,
        state,
        maps,
        server_runs,
        server_iterations,
    )
    public_maps = [
        {key: value for key, value in entry.items() if not key.startswith("_")}
        for entry in maps
    ]
    return {
        "schema_version": 1,
        "captured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "environment": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
        },
        "inputs": {
            "content_commit": _git_commit(root),
            "content_v1_baseline_sha256": lock["sha256"],
            "syntax_implementation_sha256": _implementation_digest(root),
            "tools_commit": _git_commit(tools_root),
            "workspace_commit": _git_commit(workspace_root),
            "workspace_runner_sha256": _workspace_runner_digest(workspace_root),
            "topology_components": topology_inputs,
            "profile": profile,
            "state": state,
        },
        "representative_maps": public_maps,
        "prototype": prototype,
        "collection": collection,
        "checker": checker,
        "server": server,
    }


def _bounded_count(value: str) -> int:
    number = int(value)
    if number < 1 or number > 100:
        raise argparse.ArgumentTypeError("iteration count must be 1-100")
    return number


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(
        description="Measure the current content pipeline and syntax prototypes"
    )
    command.add_argument("--root", type=Path, default=ROOT)
    command.add_argument("--workspace-root", type=Path, required=True)
    command.add_argument("--tools-root", type=Path, required=True)
    command.add_argument("--profile", default="syntax-decision")
    command.add_argument("--state", default="syntax-benchmark")
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--prototype-iterations", type=_bounded_count, default=20)
    command.add_argument("--collection-iterations", type=_bounded_count, default=3)
    command.add_argument("--checker-iterations", type=_bounded_count, default=5)
    command.add_argument("--server-runs", type=_bounded_count, default=5)
    command.add_argument("--server-iterations", type=_bounded_count, default=9)
    return command


def _safe_build_root(root: Path) -> Path:
    build_root = root / "build"
    if build_root.is_symlink():
        raise PrototypeError("build output directory must not be a symbolic link")
    build_root.mkdir(exist_ok=True)
    if not build_root.is_dir():
        raise PrototypeError("build output path must be a directory")
    return build_root.resolve()


def _write_report(root: Path, output: Path, report: dict[str, Any]) -> None:
    build_root = _safe_build_root(root)
    output = output if output.is_absolute() else root / output
    if output.is_symlink():
        raise PrototypeError("benchmark output must not be a symbolic link")
    parent = output.parent.resolve()
    try:
        parent.relative_to(build_root)
    except ValueError as error:
        raise PrototypeError("benchmark output must be below build/") from error
    parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=".syntax-benchmark-",
            suffix=".json",
            dir=parent,
            delete=False,
        ) as temporary:
            temporary.write(encoded)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, output)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    options = parser().parse_args(argv)
    try:
        report = benchmark(
            options.root,
            options.workspace_root,
            options.tools_root,
            profile=options.profile,
            state=options.state,
            prototype_iterations=options.prototype_iterations,
            collection_iterations=options.collection_iterations,
            checker_iterations=options.checker_iterations,
            server_runs=options.server_runs,
            server_iterations=options.server_iterations,
        )
        _write_report(options.root.resolve(strict=True), options.output, report)
    except (OSError, PrototypeError, subprocess.TimeoutExpired, ValueError) as error:
        print("error: {}".format(error), file=sys.stderr)
        return 1
    print("authored syntax benchmark: wrote {}".format(options.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
