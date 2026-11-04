"""Export dataset-store pair directories with content-derived opaque IDs."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tomllib
from pathlib import Path

from item_spec_languages import ALT_VERSIONS
from tiers import padded_is_evidence

ALT_GOOD = "alt-good"


def _alt_good_fields(pair: dict) -> dict:
    """Mark an alt-good pair as preference-neutral; it carries no quality label.

    Alt-good versions are good in a different style, not a quality delta, so the
    manifest records the preference role and never a direction or label.
    """
    alt_names = set(ALT_VERSIONS)
    for side in ("left", "right"):
        filename = Path(str(pair.get(side, ""))).stem
        role = pair.get(f"{side}_role")
        if filename in alt_names and role != ALT_GOOD:
            raise ValueError(f"alt version {filename} must have role alt-good")
        if role == ALT_GOOD and (side != "right" or filename not in alt_names):
            raise ValueError(
                f"alt-good role requires a right-side alt version: {side}={filename}"
            )
    if pair.get("right_role") != ALT_GOOD:
        return {}
    if pair.get("preference_neutral") is not True:
        raise ValueError(
            f"alt-good pair must set preference_neutral true: {pair.get('pair_id', '')}"
        )
    return {"role": ALT_GOOD, "preference_neutral": True}


def _export_pair(
    pair: dict, pair_file: Path, source_manifest: dict, output: Path
) -> None:
    left = pair_file.parent / pair["left"]
    right = pair_file.parent / pair["right"]
    tests = list(pair_file.parent.glob("behaviour_test.*"))
    if not left.is_file() or not right.is_file() or len(tests) != 1:
        raise ValueError(
            f"pair needs left, right, and one behaviour test: {pair_file.parent}"
        )
    hashes = {}
    digest = hashlib.sha256()
    for source in (left, right, tests[0]):
        content_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        hashes[source.name] = content_hash
        digest.update(source.suffix.encode() + b"\0" + source.read_bytes() + b"\0")
    pair_id = digest.hexdigest()[:32]
    destination = output / pair_id
    destination.mkdir(parents=True, exist_ok=True)
    names = (
        (left, f"a{left.suffix}"),
        (right, f"b{right.suffix}"),
        (tests[0], tests[0].name),
    )
    for source, name in names:
        shutil.copy2(source, destination / name)
    group_id = str(
        pair.get(
            "pair_group_id",
            pair.get("task_id", pair.get("task", pair_file.parent.parent.name)),
        )
    )
    manifest_values = {
        "id": pair_id,
        "pair_group_id": group_id,
        "language": pair.get(
            "language", source_manifest.get("language", left.suffix.lstrip("."))
        ),
        "task": pair.get("task", source_manifest.get("task", group_id)),
        "left": f"a{left.suffix}",
        "right": f"b{right.suffix}",
        "behaviour_test": tests[0].name,
    }
    task_id = str(pair.get("task", source_manifest.get("task", group_id)))
    is_category_b = "b" in pair_file.parent.parts
    includes_padded = left.stem == "padded" or right.stem == "padded"
    if is_category_b and includes_padded:
        manifest_values["padded_evidence"] = padded_is_evidence(task_id)
    manifest_values.update(_alt_good_fields(pair))
    manifest_text = "".join(
        f"{key} = "
        f"{json.dumps(value) if isinstance(value, bool) else json.dumps(str(value))}\n"
        for key, value in manifest_values.items()
    )
    license_name = pair.get("license", source_manifest.get("license"))
    if license_name is not None:
        manifest_text += f"license = {json.dumps(str(license_name))}\n"
    manifest_text += "[sha256]\n"
    manifest_text += "".join(
        f"{key} = {json.dumps(value)}\n"
        for key, value in (
            ("a", hashes[left.name]),
            ("b", hashes[right.name]),
            ("behaviour_test", hashes[tests[0].name]),
        )
    )
    (destination / "manifest.toml").write_text(manifest_text)


def export(items: Path, output: Path) -> int:
    if not items.is_dir():
        raise FileNotFoundError(f"items directory does not exist: {items}")
    output.mkdir(parents=True, exist_ok=True)
    count = 0
    for pair_file in sorted(items.rglob("pair.json")):
        pair_data = json.loads(pair_file.read_text())
        source_manifest_path = pair_file.parent / "manifest.toml"
        source_manifest = (
            tomllib.loads(source_manifest_path.read_text())
            if source_manifest_path.exists()
            else {}
        )
        pairs = pair_data.get("pairs")
        if pairs is None:
            pairs = [pair_data]
        for iter_pair in pairs:
            pair = {
                **iter_pair,
                **{
                    key: pair_data[key]
                    for key in ("pair_group_id", "task", "language")
                    if key in pair_data
                },
            }
            _export_pair(pair, pair_file, source_manifest, output)
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--items", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.items.is_dir():
        parser.error(f"items directory does not exist: {args.items}")
    try:
        print(f"exported {export(args.items, args.output)} pair(s)")
    except (FileNotFoundError, ValueError, KeyError) as error:
        print(error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
