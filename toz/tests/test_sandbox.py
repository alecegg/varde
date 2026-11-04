from dataclasses import replace
from pathlib import Path

import pytest
from varde_toz.sandbox import (
    CheckedPolicy,
    Policy,
    bubblewrap_args,
    check_policy,
    seatbelt_profile,
)


def checked_fixture_policy() -> CheckedPolicy:
    return CheckedPolicy(
        read_roots=(Path("/fixture/read"),),
        write_roots=(Path("/fixture/write"),),
        scratch_dir=Path("/fixture/scratch"),
        network=False,
        executable=Path("/fixture/bin/worker"),
        cwd=Path("/fixture/read"),
        protected_roots=(Path("/fixture/store"),),
    )


def test_seatbelt_grants_workspace_and_denies_network_by_default() -> None:
    # varde-toz skill troubleshooting: Seatbelt grants workspace read/write and
    # no network unless the policy opts in.
    profile = seatbelt_profile(checked_fixture_policy())
    assert "(deny default)" in profile
    assert "allow network" not in profile
    assert '(allow file-write* (subpath "/fixture/write"))' in profile
    assert '(deny file-read* file-write* (subpath "/fixture/store"))' in profile

    network = seatbelt_profile(replace(checked_fixture_policy(), network=True))
    assert "allow network" in network


def test_policy_allows_workspace_writes_and_rejects_outside_paths(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    scratch = tmp_path / "scratch"
    store = tmp_path / "store"
    for path in (workspace, outside, scratch, store):
        path.mkdir()
    executable = workspace / "worker"
    executable.touch()
    checked = check_policy(
        Policy((workspace,), (workspace,), scratch, protected_roots=(store,)),
        executable,
        workspace,
    )
    profile = seatbelt_profile(checked)
    assert f'(allow file-write* (subpath "{workspace}"))' in profile
    assert f'(deny file-read* file-write* (subpath "{store}"))' in profile
    with pytest.raises(ValueError, match="not permitted"):
        check_policy(
            Policy((), (), scratch, protected_roots=(store,)),
            executable,
            outside,
        )


def test_bubblewrap_policy_mounts_workspace_writable_and_shares_network_opt_in() -> (
    None
):
    args = bubblewrap_args(checked_fixture_policy(), ("--flag", "value"))
    assert ("--bind", "/fixture/write", "/fixture/write") in tuple(
        tuple(args[index : index + 3]) for index in range(len(args) - 2)
    )
    assert "--share-net" not in args
    assert args[-6:] == (
        "--chdir",
        "/fixture/read",
        "--",
        "/fixture/bin/worker",
        "--flag",
        "value",
    )
    network = bubblewrap_args(replace(checked_fixture_policy(), network=True))
    assert "--share-net" in network


def test_check_policy_rejects_protected_store_overlap(tmp_path: Path) -> None:
    store = tmp_path / "store"
    scratch = tmp_path / "scratch"
    executable = tmp_path / "worker"
    store.mkdir()
    scratch.mkdir()
    executable.touch()
    policy = Policy(
        read_roots=(tmp_path,),
        write_roots=(),
        scratch_dir=scratch,
        protected_roots=(store,),
    )
    with pytest.raises(ValueError, match="overlaps protected store"):
        check_policy(policy, executable, tmp_path)


def test_check_policy_requires_protected_store(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    executable = tmp_path / "worker"
    executable.touch()
    with pytest.raises(ValueError, match="requires a protected store path"):
        check_policy(Policy((), (), scratch), executable, tmp_path)


def test_check_policy_returns_canonical_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    scratch = tmp_path / "scratch"
    store = tmp_path / "store"
    workspace.mkdir()
    scratch.mkdir()
    store.mkdir()
    executable = workspace / "worker"
    executable.touch()
    checked = check_policy(
        Policy((workspace,), (), scratch, protected_roots=(store,)),
        executable,
        workspace,
    )
    assert checked.cwd == workspace.resolve()
    assert checked.executable == executable.resolve()
    assert checked.scratch_dir == scratch.resolve()
