#!/usr/bin/env python3
"""Validate the 7Soul1 library and the fixed player-status face mapping."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path
import re
import struct
import zipfile

SOURCE_SHA256 = "82167b463d20fdc2c0cb641e061503bb77816558087270e50eb66ad34cf75658"
EXPECTED_COUNTS = {
    "armor": 19,
    "accessories": 14,
    "materials": 17,
    "items": 97,
    "potions": 57,
    "skills": 154,
    "weapons": 138,
}
PREFIX_TO_CATEGORY = {
    "A_": "armor",
    "C_": "armor",
    "Ac_": "accessories",
    "E_": "materials",
    "I_": "items",
    "P_": "potions",
    "S_": "skills",
    "W_": "weapons",
}
STATUS_OUTPUTS = {
    "blindness": "blindness.101",
    "confusion": "confusion.101",
    "depletion": "depletion.101",
    "soul depletion": "soul_depletion.101",
    "poisoning": "poisoning.101",
    "slowness": "slowness.101",
    "strength self": "icon_strength_self.101",
    "protection from cold": "icon_prot_cold.101",
    "protection from fire": "icon_prot_fire.101",
    "protection from electricity": "icon_prot_elec.101",
    "protection from poison": "icon_prot_poison.101",
    "word of recall": "icon_word_of_recall.101",
    "athlete's foot": "atheletes_foot.101",
    "the runs": "diarrhea.101",
    "cold": "disease_cold.101",
    "flu": "flu.101",
    "leprosy": "leprosy.101",
    "pneumonic plague": "pneumonic_plague.101",
    "smallpox": "smallpox.101",
    "tapeworms": "tapeworms.101",
    "warts": "warts.101",
    "paralysis": "paralysis.101",
    "jail sentence": "jail.101",
}
ARC_FACES = {
    "arch/forces/blindness.arc": "blindness.101",
    "arch/forces/confusion.arc": "confusion.101",
    "arch/forces/depletion.arc": "depletion.101",
    "arch/forces/poisoning.arc": "poisoning.101",
    "arch/forces/slowness.arc": "slowness.101",
    "arch/forces/soul_depletion.arc": "soul_depletion.101",
    "arch/forces/disease/atheletes_foot.arc": "atheletes_foot.101",
    "arch/forces/disease/diarrhea.arc": "diarrhea.101",
    "arch/forces/disease/disease_cold.arc": "disease_cold.101",
    "arch/forces/disease/flu.arc": "flu.101",
    "arch/forces/disease/leprosy.arc": "leprosy.101",
    "arch/forces/disease/pneumonic_plague.arc": "pneumonic_plague.101",
    "arch/forces/disease/smallpox.arc": "smallpox.101",
    "arch/forces/disease/tapeworms.arc": "tapeworms.101",
    "arch/forces/disease/warts.arc": "warts.101",
    "arch/intern/spells/word_of_recall.arc": "icon_word_of_recall.101",
    "arch/intern/spells/strength_self.arc": "icon_strength_self.101",
    "arch/intern/spells/protection_from_cold.arc": "icon_prot_cold.101",
    "arch/intern/spells/protection_from_fire.arc": "icon_prot_fire.101",
    "arch/intern/spells/protection_from_electricity.arc": "icon_prot_elec.101",
    "arch/intern/spells/protection_from_poison.arc": "icon_prot_poison.101",
}


def png_metadata(path: Path) -> tuple[int, int, int, int]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError(f"{path} is not a valid PNG")
    width, height, depth, color_type, compression, filtering, interlace = struct.unpack(">IIBBBBB", data[16:29])
    return width, height, depth, color_type


def source_face(source_name: str) -> tuple[str, str]:
    prefix = next((key for key in sorted(PREFIX_TO_CATEGORY, key=len, reverse=True) if source_name.startswith(key)), None)
    if prefix is None:
        raise ValueError(f"source icon has no category: {source_name}")
    stem = Path(source_name).stem.lower()
    return PREFIX_TO_CATEGORY[prefix], f"icon_7soul1_{stem}.101"


def validate(root: Path, archive: Path | None = None) -> dict[str, int]:
    library = root / "arch/intern/icons/7soul1"
    if not library.is_dir():
        raise ValueError("missing 7Soul1 icon library")
    paths = {category: sorted((library / category).glob("*.png")) for category in EXPECTED_COUNTS}
    if {category: len(items) for category, items in paths.items()} != EXPECTED_COUNTS:
        raise ValueError("7Soul1 category counts do not match 19/14/17/97/57/154/138")
    all_paths = [path for items in paths.values() for path in items]
    if len(all_paths) != 496:
        raise ValueError("7Soul1 library must contain exactly 496 PNGs")
    face_names = [path.stem for path in all_paths]
    if len(face_names) != len(set(face_names)) or not all(re.fullmatch(r"icon_7soul1_[a-z0-9_]+\.101", name) for name in face_names):
        raise ValueError("7Soul1 face names are not unique and canonical")
    for path in all_paths:
        if png_metadata(path) != (34, 34, 8, 6):
            raise ValueError(f"canonical icon is not RGBA 34x34: {path}")

    source_map = library / "SOURCE_MAP.tsv"
    with source_map.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source, delimiter="\t"))
    if source_map.read_text(encoding="utf-8").splitlines()[0] != "upstream_filename\tatrinik_face\tsha256\tmodification":
        raise ValueError("SOURCE_MAP.tsv has an invalid header")
    if len(rows) != 496 or len({row["upstream_filename"] for row in rows}) != 496:
        raise ValueError("SOURCE_MAP.tsv must contain one row for each of 496 icons")
    for row in rows:
        category, face = source_face(row["upstream_filename"])
        path = library / category / f"{face}.png"
        if row["atrinik_face"] != face or row["modification"] != "none (byte-identical source copy)":
            raise ValueError(f"invalid provenance row for {row['upstream_filename']}")
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError(f"provenance digest mismatch for {row['upstream_filename']}")

    if archive is not None:
        archive_bytes = archive.read_bytes()
        if hashlib.sha256(archive_bytes).hexdigest() != SOURCE_SHA256:
            raise ValueError("source archive digest mismatch")
        with zipfile.ZipFile(archive) as source:
            entries = sorted(name for name in source.namelist() if name.lower().endswith(".png"))
            if len(entries) != 496 or any("/" in name for name in entries):
                raise ValueError("source archive must contain exactly 496 flat PNGs")
            for name in entries:
                category, face = source_face(Path(name).name)
                if (library / category / f"{face}.png").read_bytes() != source.read(name):
                    raise ValueError(f"canonical icon differs from source archive: {name}")

    status_map = library / "STATUS_SOURCE_MAP.tsv"
    with status_map.open(newline="", encoding="utf-8") as source:
        status_rows = list(csv.DictReader(source, delimiter="\t"))
    if len(status_rows) != len(STATUS_OUTPUTS) or {row["status"] for row in status_rows} != set(STATUS_OUTPUTS):
        raise ValueError("STATUS_SOURCE_MAP.tsv does not cover all 23 fixed statuses")
    for row in status_rows:
        output_face = STATUS_OUTPUTS[row["status"]]
        if row["output_face"] != output_face:
            raise ValueError(f"invalid status output mapping: {row['status']}")
        source_face_name = row["imported_source_face"]
        if not re.fullmatch(r"icon_7soul1_[a-z0-9_]+\.101", source_face_name):
            raise ValueError(f"invalid imported source face: {source_face_name}")
        source_path = next((path for path in all_paths if path.stem == source_face_name), None)
        if source_path is None:
            raise ValueError(f"status source is not in the imported library: {source_face_name}")
        output_path = next(root.rglob(f"{output_face}.png"), None)
        if output_path is None or png_metadata(output_path) != (32, 32, 8, 6):
            raise ValueError(f"status output is missing or not RGBA 32x32: {output_face}")
    for relative, expected_face in ARC_FACES.items():
        text = (root / relative).read_text(encoding="utf-8")
        if f"face {expected_face}" not in text:
            raise ValueError(f"{relative} does not publish {expected_face}")
    jail = (root / "maps/python/Jail.py").read_text(encoding="utf-8")
    if '"jail.101"' not in jail:
        raise ValueError("Jail.py does not publish jail.101")
    return {"canonical": len(all_paths), "statuses": len(status_rows)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    result = validate(args.root.resolve(), args.archive.resolve() if args.archive else None)
    print(f"status icons: {result['canonical']} canonical imports and {result['statuses']} fixed statuses validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
