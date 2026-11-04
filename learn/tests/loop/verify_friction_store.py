#!/usr/bin/env python3
"""Compare a copied friction store with the pre-migration implementation."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[3]
BASELINE = "bab1ae6d"
GOLDEN = Path(__file__).parent / "golden" / "friction"
REPO_VAR = "VARDE_LEARN_STORE"
CLI_RUNNER = (
    "import sys; from varde_learn.loop import cli_friction; "
    "raise SystemExit(cli_friction.run(sys.argv[1:]))"
)


class VerificationFailure(Exception):
    """A store assertion failed."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationFailure(message)


def copy_store(source: Path, destination: Path) -> None:
    source = source.expanduser().resolve(strict=True)
    require(source.is_dir(), f"store path is not a directory: {source}")
    for path in source.rglob("*"):
        require(not path.is_symlink(), f"store contains a symlink: {path}")
    shutil.copytree(source, destination, copy_function=shutil.copyfile)


def run_cli(
    store: Path, args: list[str], *, import_paths: tuple[Path, ...] = ()
) -> str:
    env = os.environ.copy()
    env[REPO_VAR] = str(store)
    env["PYTHONPATH"] = os.pathsep.join(
        [*(str(path) for path in import_paths), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    result = subprocess.run(  # noqa: S603 - arguments are passed without a shell.
        [sys.executable, "-c", CLI_RUNNER, *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        check=False,
        text=True,
    )
    require(
        result.returncode == 0,
        f"command {' '.join(args)} failed ({result.returncode}): "
        f"{result.stderr.strip() or result.stdout.strip()}",
    )
    return result.stdout


def json_output(
    store: Path, args: list[str], *, import_paths: tuple[Path, ...] = ()
) -> Any:
    output = run_cli(store, args, import_paths=import_paths)
    try:
        return json.loads(output)
    except json.JSONDecodeError as error:
        raise VerificationFailure(
            f"command {' '.join(args)} did not return JSON"
        ) from error


def database_dump(path: Path) -> dict[str, list[list[Any]]]:
    with sqlite3.connect(path) as db:
        names = [
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        result = {
            name: [
                list(row)
                for row in db.execute(
                    f'SELECT * FROM "{name}" ORDER BY rowid'  # noqa: S608 - names come from sqlite_master.
                )
            ]
            for name in names
        }
    log_path = path.with_name("friction.jsonl")
    log_bytes = log_path.read_bytes() if log_path.exists() else b""
    return normalize_database_dump(result, log_bytes)


def normalize_database_dump(
    tables: dict[str, list[list[Any]]], log_bytes: bytes | None = None
) -> dict[str, list[list[Any]]]:
    for row in tables.get("meta", []):
        if row[0] == "log_bytes":
            if log_bytes is not None:
                row[1] = str(len(log_bytes))
        elif row[0] == "log_hash":
            if log_bytes is not None:
                row[1] = hashlib.sha256(log_bytes).hexdigest()
        elif row[0] == "log_map":
            row[1] = json.dumps(
                json.loads(row[1]), sort_keys=True, separators=(",", ":")
            )
    return tables


def canonical_dump(value: dict[str, list[list[Any]]]) -> str:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    )


def archive_baseline(destination: Path) -> Path:
    destination.mkdir(parents=True)
    git = shutil.which("git")
    if git is None:
        raise VerificationFailure(
            "git is required to extract the pre-migration baseline"
        )
    archive = subprocess.run(  # noqa: S603 - fixed git subcommand; no shell is used.
        [git, "-C", str(ROOT), "archive", BASELINE, "learn", "core", "data"],
        check=True,
        capture_output=True,
    )
    with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as tar:
        tar.extractall(destination, filter="data")
    return destination


def compare_cli(old_store: Path, new_store: Path, old_paths: tuple[Path, ...]) -> None:
    old_list = json_output(
        old_store, ["friction", "list", "--json"], import_paths=old_paths
    )
    new_list = json_output(new_store, ["friction", "list", "--json"])
    require(old_list == new_list, "friction list --json differs from baseline")
    old_items = old_list.get("data", {}).get("items", [])
    new_items = new_list.get("data", {}).get("items", [])
    require(old_items == new_items, "friction list --json differs from baseline")
    require(
        {(item["id"], item["slug"]) for item in old_items}
        == {(item["id"], item["slug"]) for item in new_items},
        "friction item IDs/slugs differ from baseline",
    )
    require(bool(old_items), "store contains no friction items to compare")
    first_id = str(old_items[0]["id"])
    old_show = json_output(
        old_store, ["friction", "show", first_id, "--json"], import_paths=old_paths
    )
    new_show = json_output(new_store, ["friction", "show", first_id, "--json"])
    require(old_show == new_show, "friction show --json differs from baseline")
    for prefix in (
        ["friction", "list", "--status", "open"],
        ["adopt", "recurrence"],
    ):
        old = json_output(old_store, [*prefix, "--json"], import_paths=old_paths)
        new = json_output(new_store, [*prefix, "--json"])
        require(old == new, f"{' '.join(prefix)} --json differs from baseline")
    with (
        tempfile.TemporaryDirectory(prefix="varde-friction-export-") as old_dir,
        tempfile.TemporaryDirectory(prefix="varde-friction-export-") as new_dir,
    ):
        old = json_output(
            old_store,
            ["friction", "export", "--json", old_dir],
            import_paths=old_paths,
        )
        new = json_output(new_store, ["friction", "export", "--json", new_dir])
        require(old == new, "friction export --json differs from baseline")
        require(
            sorted(path.name for path in Path(old_dir).iterdir())
            == sorted(path.name for path in Path(new_dir).iterdir()),
            "friction export filenames differ from baseline",
        )
        for old_file in Path(old_dir).iterdir():
            new_file = Path(new_dir) / old_file.name
            require(
                old_file.read_bytes() == new_file.read_bytes(),
                f"friction export differs for {old_file.name}",
            )


def check_read_commands_preserve_log(store: Path) -> None:
    log = store / "friction.jsonl"
    before = log.read_bytes()
    data = json.loads(run_cli(store, ["friction", "list", "--json"]))
    items = data.get("data", {}).get("items", [])
    require(bool(items), "store contains no friction items")
    run_cli(store, ["friction", "show", str(items[0]["id"]), "--json"])
    with tempfile.TemporaryDirectory(prefix="varde-friction-export-") as directory:
        run_cli(store, ["friction", "export", "--json", directory])
    run_cli(store, ["friction", "list", "--status", "open", "--json"])
    run_cli(store, ["adopt", "recurrence", "--json"])
    after = log.read_bytes()
    require(
        before == after,
        "read/list/show/export/status/adopt queries changed friction.jsonl",
    )


def check_event_import(store: Path) -> None:
    log = store / "friction.jsonl"
    before = log.read_bytes()
    with tempfile.TemporaryDirectory(prefix="varde-friction-events-") as directory:
        export_path = Path(directory) / "events.md"
        run_cli(store, ["friction", "export", "--md", "--out", str(export_path)])
        exported_events = sum(
            line.startswith("{")
            for line in export_path.read_text(encoding="utf-8").splitlines()
        )
        output = run_cli(store, ["friction", "import", "--dry-run", str(export_path)])
    require(
        "0 new friction events" in output,
        f"dry-run import of exported events was not empty: {output.strip()}",
    )
    require(
        "already present" in output, "dry-run import did not report existing events"
    )
    match = re.fullmatch(
        r"Would import 0 new friction events; (\d+) already present\.",
        output.strip(),
    )
    if match is None:
        raise VerificationFailure(
            f"dry-run import did not report zero adds: {output.strip()}"
        )
    present = int(match.group(1))
    require(
        0 < present <= exported_events,
        "dry-run import did not recognize exported events already in the store: "
        f"present={present}; exported={exported_events}",
    )
    require(log.read_bytes() == before, "dry-run event import changed friction.jsonl")


def check_status_and_adoption_append_only(store: Path) -> None:
    log = store / "friction.jsonl"
    before = log.read_bytes()
    result = json.loads(run_cli(store, ["friction", "list", "--json"]))
    items = result.get("data", {}).get("items", [])
    require(bool(items), "store contains no friction items for status/adoption checks")
    item_id = str(items[0]["id"])
    run_cli(
        store,
        [
            "friction",
            "set-status",
            "--reason",
            "store verification copy",
            "--json",
            item_id,
            "resolved",
        ],
    )
    run_cli(
        store,
        [
            "adopt",
            "record",
            "--items",
            item_id,
            "--summary",
            "Store verification copy",
            "--files",
            "verification.txt",
            "--json",
        ],
    )
    after = log.read_bytes()
    require(
        after.startswith(before),
        "status/adoption rewrote existing friction.jsonl bytes",
    )
    appended = after[len(before) :]
    require(bool(appended), "status/adoption operations appended no events")
    require(appended.endswith(b"\n"), "status/adoption left a partial event line")
    for line in appended.splitlines():
        event = json.loads(line)
        require(
            event.get("kind") in {"status_changed", "adoption_recorded"},
            "unexpected appended event",
        )


def check_rebuild_matches_baseline(
    new_store: Path, old_store: Path | None, golden_dump: Path | None = None
) -> None:
    old_tables = (
        database_dump(old_store / "learn.db") if old_store is not None else None
    )
    expected_tables = (
        old_tables
        if old_tables is not None
        else json.loads(golden_dump.read_text(encoding="utf-8"))
        if golden_dump is not None
        else None
    )
    if not isinstance(expected_tables, dict):
        raise VerificationFailure("no baseline database dump is available")
    expected_tables = normalize_database_dump(expected_tables)
    old_dump = canonical_dump(expected_tables)
    id_map = next(
        (
            json.loads(row[1])
            for row in expected_tables.get("meta", [])
            if row[0] == "log_map"
        ),
        None,
    )
    if not isinstance(id_map, dict):
        raise VerificationFailure("baseline database dump has no id map")
    database = new_store / "learn.db"
    for suffix in ("", "-wal", "-shm"):
        path = new_store / f"learn.db{suffix}"
        if path.exists():
            path.unlink()
    map_path = new_store / "learn.db.pre-log.map"
    map_path.write_text(
        json.dumps(
            cast("dict[str, dict[str, int | str]]", id_map), separators=(",", ":")
        ),
        encoding="utf-8",
    )
    run_cli(new_store, ["friction", "list", "--json"])
    require(not map_path.exists(), "cache rebuild did not consume the preserved ID map")
    rebuilt_tables = database_dump(database)
    rebuilt = canonical_dump(rebuilt_tables)
    if rebuilt != old_dump:
        differences = []
        for table in sorted(set(expected_tables) | set(rebuilt_tables)):
            wanted = expected_tables.get(table, [])
            actual = rebuilt_tables.get(table, [])
            if wanted != actual:
                wanted_rows = {json.dumps(row, sort_keys=True) for row in wanted}
                actual_rows = {json.dumps(row, sort_keys=True) for row in actual}
                differences.append(
                    f"{table}: expected {len(wanted)} rows, got {len(actual)}; "
                    f"missing={sorted(wanted_rows - actual_rows)[:2]!r}; "
                    f"extra={sorted(actual_rows - wanted_rows)[:2]!r}"
                )
        detail = "; ".join(differences) or "tables differ"
        raise VerificationFailure(
            f"full cache rebuild differs from baseline database dump ({detail})"
        )
    require(rebuilt == old_dump, "full cache rebuild differs from old learn.db")


def check_legacy_only_migration() -> None:
    legacy = Path(__file__).parents[2] / "../data/tests/fixtures/friction/legacy-no-log"
    legacy = legacy.resolve()
    with tempfile.TemporaryDirectory(prefix="varde-friction-legacy-") as directory:
        store = Path(directory) / "store"
        store.mkdir()
        shutil.copyfile(legacy / "learn.db", store / "learn.db")
        before = database_dump(store / "learn.db")["items"]
        result = json.loads(run_cli(store, ["friction", "list", "--json"]))
        items = result.get("data", {}).get("items", [])
        require(len(items) == len(before), "legacy-only migration lost an item")
        require(
            (store / "learn.db.pre-log").is_file(), "legacy database backup is missing"
        )


def legacy_ledger_rows(raw: bytes) -> list[dict[str, Any]]:
    """Parse analyzed.jsonl bytes as the pre-repository code did."""
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return []
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        required = ("session", "harness", "analyzed_at")
        if isinstance(record, dict) and all(
            isinstance(record.get(key), str) and record[key] for key in required
        ):
            latest[(record["harness"], record["session"])] = record
    return list(latest.values())


def legacy_digest(raw: bytes | None, day: str) -> dict[str, Any] | None:
    """Parse one digest file as the pre-repository code did."""
    if raw is None:
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
    except ValueError:
        return None
    if not isinstance(value, dict) or not isinstance(value.get("text"), str):
        return None
    return {
        "date": day,
        "text": value["text"],
        "candidates": value.get("candidates", []),
    }


def digest_files(store: Path) -> dict[str, bytes | None]:
    directory = store / "digests"
    if not directory.is_dir():
        return {}
    return {
        path.name: path.read_bytes() if path.is_file() else None
        for path in sorted(directory.glob("*.json"))
    }


def check_ledger_and_digests(store: Path) -> None:
    """Check ledger and digest reads and appends on a store copy."""
    from varde_learn.loop import analyzed, sweep_digest

    ledger_path = store / "analyzed.jsonl"
    ledger_before = ledger_path.read_bytes() if ledger_path.exists() else b""
    require(
        analyzed.read_all(store) == legacy_ledger_rows(ledger_before),
        "analyzed.jsonl repository read differs from legacy parse",
    )
    digests_before = digest_files(store)
    for name, raw in digests_before.items():
        try:
            day = date.fromisoformat(name.removesuffix(".json"))
        except ValueError:
            continue
        require(
            sweep_digest.read_digest(store, day) == legacy_digest(raw, day.isoformat()),
            f"digest {name} repository read differs from legacy parse",
        )
    analyzed.mark(store, "verify", "verify-session", "2999-01-01T00:00:00Z", "gate")
    ledger_after = ledger_path.read_bytes()
    require(
        ledger_after.startswith(ledger_before) and ledger_after != ledger_before,
        "analyzed.jsonl mark did not append only",
    )
    require(ledger_after.endswith(b"\n"), "analyzed.jsonl mark left a partial line")
    sweep_digest.write_digest(store, date(2999, 1, 1), "gate", [])
    digests_after = digest_files(store)
    require(
        all(digests_after.get(name) == raw for name, raw in digests_before.items()),
        "digest write changed an existing digest file",
    )
    require("2999-01-01.json" in digests_after, "digest write added no file")


def verify(source: Path, *, golden_dump: Path | None = None) -> list[str]:
    report: list[str] = []

    def passed(message: str) -> None:
        report.append(message)
        print(message, flush=True)

    with tempfile.TemporaryDirectory(prefix="varde-friction-verify-") as temp:
        temp_root = Path(temp)
        original_copy = temp_root / "source-copy"
        copy_store(source, original_copy)
        old_store = temp_root / "old-store"
        new_store = temp_root / "new-store"
        shutil.copytree(original_copy, old_store, copy_function=shutil.copyfile)
        shutil.copytree(original_copy, new_store, copy_function=shutil.copyfile)
        if golden_dump is None:
            old_root = archive_baseline(temp_root / "baseline")
            old_paths = tuple(
                old_root / path for path in ("learn/src", "core/src", "data/src")
            )
            compare_cli(old_store, new_store, old_paths)
            passed(
                "PASS old/new list, show, status filters, export, recurrences, "
                "IDs and slugs"
            )
            comparison_store: Path | None = old_store
        else:
            comparison_store = None
            passed("PASS synthetic golden event log loaded")
        if comparison_store is None:
            check_read_commands_preserve_log(new_store)
        else:
            require(
                (new_store / "friction.jsonl").read_bytes()
                == (original_copy / "friction.jsonl").read_bytes(),
                "old/new CLI reads changed friction.jsonl bytes",
            )
            require(
                (old_store / "friction.jsonl").read_bytes()
                == (original_copy / "friction.jsonl").read_bytes(),
                "old CLI reads changed friction.jsonl bytes",
            )
        passed("PASS read and query commands preserve friction.jsonl bytes")
        check_event_import(new_store)
        passed("PASS exported event dry-run import adds zero events")
        mutation_store = temp_root / "mutation-store"
        shutil.copytree(original_copy, mutation_store, copy_function=shutil.copyfile)
        check_status_and_adoption_append_only(mutation_store)
        passed("PASS status and adoption operations only append complete event lines")
        check_rebuild_matches_baseline(new_store, comparison_store, golden_dump)
        passed("PASS full cache rebuild matches old database dump")
        ledger_store = temp_root / "ledger-store"
        shutil.copytree(original_copy, ledger_store, copy_function=shutil.copyfile)
        check_ledger_and_digests(ledger_store)
        passed("PASS analyzed ledger and digests match legacy parse and append only")
    check_legacy_only_migration()
    passed("PASS legacy database-only migration preserves entries")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "store", type=Path, help="friction store directory to copy and verify"
    )
    parser.add_argument(
        "--golden-dump",
        type=Path,
        help=(
            "compare against the checked-in canonical dump instead of the old database"
        ),
    )
    args = parser.parse_args()
    try:
        verify(args.store, golden_dump=args.golden_dump)
    except (
        VerificationFailure,
        OSError,
        subprocess.CalledProcessError,
        sqlite3.Error,
    ) as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1
    print("PASS friction store verification")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
