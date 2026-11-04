from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from varde_learn.loop.diagnose import (
    ContextUsageHarness,
    DiagnosticHarness,
    ListHarness,
    ListRequest,
    NormalizedRecordBudget,
    list_sessions,
    register_harness,
)
from varde_learn.loop.diagnose.context_usage import ContextUsage, context_usage
from varde_learn.loop.session_link import CandidateSession, ParentSession, link_workers


def _usage_session(
    harness: ContextUsageHarness, path: Path, *records: dict
) -> ContextUsage | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    return context_usage(harness, path)


def test_worker_links_are_unique_and_report_ambiguity() -> None:
    parents = [
        ParentSession("parent-b", ("started child-1", "again child-1")),
        ParentSession("parent-a", ("started child-1",)),
    ]
    links = link_workers(
        parents, [CandidateSession("child-1"), CandidateSession("child-2")]
    )
    assert links == [("parent-a", "parent-b"), None]


def test_worker_link_keeps_first_evidence_from_unique_parent() -> None:
    links = link_workers(
        [ParentSession("parent", ("first child-1", "second child-1"))],
        [CandidateSession("child-1")],
    )
    link = links[0]
    assert link is not None and not isinstance(link, tuple)
    assert link.parent_id == "parent"
    assert link.evidence == "first child-1"


def test_direct_opencode_usage_sums_supported_counters() -> None:
    sample = context_usage(
        ContextUsageHarness.OPENCODE,
        direct_usage={
            "usage": {"input": 10, "output": 3, "reasoning": 2, "cacheRead": 5},
            "model": {"id": "m", "contextWindow": 100},
        },
    )
    assert sample is not None
    assert (sample.current_tokens, sample.model, sample.context_window) == (
        20,
        "m",
        100,
    )


def test_context_usage_uses_latest_snapshot_after_reset(tmp_path: Path) -> None:
    session = tmp_path / ".codex" / "sessions" / "2025-01-01" / "session.jsonl"
    session.parent.mkdir(parents=True)
    session.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "payload": {
                            "type": "token_count",
                            "info": {
                                "total_token_usage": {
                                    "input_tokens": 20,
                                    "output_tokens": 5,
                                }
                            },
                        }
                    }
                ),
                json.dumps({"type": "session_reset"}),
                json.dumps(
                    {
                        "payload": {
                            "type": "token_count",
                            "info": {
                                "last_token_usage": {
                                    "input_tokens": 4,
                                    "output_tokens": 2,
                                },
                                "model_context_window": 100,
                            },
                        }
                    }
                ),
                "",
            ]
        )
    )
    sample = context_usage(ContextUsageHarness.CODEX, session)
    assert sample is not None
    assert sample.current_tokens == 6
    assert sample.context_window == 100


def test_context_usage_rejects_symlinked_session_file(tmp_path: Path) -> None:
    actual = tmp_path / "actual.jsonl"
    actual.write_text(
        json.dumps(
            {"type": "message", "message": {"role": "assistant", "usage": {"input": 1}}}
        )
        + "\n"
    )
    session = tmp_path / ".pi" / "agent" / "sessions" / "s.jsonl"
    session.parent.mkdir(parents=True)
    session.symlink_to(actual)
    assert context_usage(ContextUsageHarness.PI, session) is None


def test_opencode_export_uses_latest_usage_after_compaction(tmp_path: Path) -> None:
    export = tmp_path / ".opencode" / "session.json"
    export.parent.mkdir()
    export.write_text(
        json.dumps(
            {
                "info": {"id": "session-1"},
                "messages": [
                    {
                        "tokens": {"input": 5, "output": 2, "cache": {"read": 3}},
                        "model": {"id": "first"},
                    },
                    {"type": "compaction"},
                    {
                        "tokens": {"input": 4, "output": 1, "cache": {"write": 2}},
                        "model": {"id": "latest"},
                    },
                ],
            }
        )
    )
    sample = context_usage(ContextUsageHarness.OPENCODE, export)
    assert sample is not None
    assert (sample.current_tokens, sample.model) == (7, "latest")


def test_context_usage_skips_json_non_object_records(tmp_path: Path) -> None:
    session = tmp_path / ".codex" / "sessions" / "session.jsonl"
    session.parent.mkdir(parents=True)
    session.write_text(
        "[]\n"
        + json.dumps(
            {
                "payload": {
                    "type": "token_count",
                    "info": {"last_token_usage": {"input_tokens": 3}},
                }
            }
        )
        + "\n"
    )
    sample = context_usage(ContextUsageHarness.CODEX, session)
    assert sample is not None
    assert sample.current_tokens == 3


def test_missing_or_malformed_usage_is_not_a_snapshot(tmp_path: Path) -> None:
    codex = _usage_session(
        ContextUsageHarness.CODEX,
        tmp_path / ".codex" / "sessions" / "session.jsonl",
        {
            "payload": {
                "type": "token_count",
                "info": {"last_token_usage": {"input_tokens": "bad"}},
            }
        },
    )
    assert codex is None
    claude = _usage_session(
        ContextUsageHarness.CLAUDE,
        tmp_path / ".claude" / "projects" / "session.jsonl",
        {"type": "assistant", "message": {"usage": {"input_tokens": -1}}},
    )
    assert claude is None


def test_provider_cache_components_follow_adapter_semantics(tmp_path: Path) -> None:
    codex = _usage_session(
        ContextUsageHarness.CODEX,
        tmp_path / ".codex" / "sessions" / "session.jsonl",
        {
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {
                        "input_tokens": 5,
                        "output_tokens": 2,
                        "cached_input_tokens": 3,
                    }
                },
            }
        },
    )
    claude = _usage_session(
        ContextUsageHarness.CLAUDE,
        tmp_path / ".claude" / "projects" / "session.jsonl",
        {
            "type": "assistant",
            "message": {
                "usage": {
                    "input_tokens": 5,
                    "cache_read_input_tokens": 3,
                    "cache_creation_input_tokens": 2,
                }
            },
        },
    )
    opencode = _usage_session(
        ContextUsageHarness.OPENCODE,
        tmp_path / ".opencode" / "session.jsonl",
        {
            "type": "message",
            "tokens": {
                "input": 5,
                "output": 2,
                "reasoning": 1,
                "cacheRead": 3,
                "cacheWrite": 2,
            },
        },
    )
    assert codex is not None and claude is not None and opencode is not None
    assert [codex.current_tokens, claude.current_tokens, opencode.current_tokens] == [
        10,
        10,
        13,
    ]


def test_pi_uses_direct_usage_or_bounded_session_file_fallback(tmp_path: Path) -> None:
    direct = context_usage(
        ContextUsageHarness.PI,
        direct_usage={
            "usage": {"input": 7, "output": 2},
            "model": {"id": "pi-model", "contextWindow": 100},
        },
    )
    assert direct is not None
    assert (direct.current_tokens, direct.model, direct.context_window) == (
        9,
        "pi-model",
        100,
    )
    session = tmp_path / ".pi/agent/sessions/pi-session.jsonl"
    session.parent.mkdir(parents=True)
    session.write_text(
        json.dumps(
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "usage": {"input": 6, "output": 1},
                    "model": {"id": "fallback"},
                },
            }
        )
        + "\n"
    )
    fallback = context_usage(ContextUsageHarness.PI, session)
    assert fallback is not None
    assert (fallback.current_tokens, fallback.model) == (7, "fallback")


def test_normalized_record_budget_tracks_replacements() -> None:
    budget = NormalizedRecordBudget()
    assert budget.try_add({"text": "short"})
    original = budget.used_bytes
    assert budget.try_replace({"text": "short"}, {"text": "longer"})
    assert budget.used_bytes > original


@dataclass
class _Session:
    harness: str
    identity: str
    session_id: str
    cwd: str
    started_at: str
    parent_identity: str | None = None
    source: str = "source.jsonl"
    retro_analyst: bool = False


class _Adapter:
    harness = DiagnosticHarness.CODEX

    def __init__(self, sessions):
        self.sessions = sessions

    def discover(self, *, repo, roots, limit):
        return self.sessions[:limit]

    def inspect(self, request):
        raise NotImplementedError


def test_listing_filters_repository_and_groups_native_children(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    sessions = [
        _Session("codex", "root", "root-session", str(repo), "2025-01-01T00:00:00Z"),
        _Session(
            "codex", "child", "child-session", str(repo), "2025-01-02T00:00:00Z", "root"
        ),
        _Session(
            "codex",
            "outside",
            "outside-session",
            str(tmp_path / "other"),
            "2025-01-03T00:00:00Z",
        ),
    ]
    from varde_learn.loop.diagnose.codex import CodexHarness
    from varde_learn.loop.diagnose.model import HARNESS_ADAPTERS

    register_harness(CodexHarness())
    monkeypatch.setitem(HARNESS_ADAPTERS, DiagnosticHarness.CODEX, _Adapter(sessions))
    result = list_sessions(
        ListRequest(ListHarness.CODEX, repo, tmp_path, tmp_path, tmp_path, limit=2)
    )
    assert [item.session_id for item in result.sessions] == ["root-session"]
    assert [item.session_id for item in result.sessions[0].workers] == ["child-session"]


def test_listing_offset_returns_roots_after_first_page(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    sessions = [
        _Session(
            "codex",
            f"root-{index}",
            f"session-{index}",
            str(repo),
            f"2025-01-{index + 1:02d}T00:00:00Z",
        )
        for index in range(12)
    ]
    from varde_learn.loop.diagnose.model import HARNESS_ADAPTERS

    monkeypatch.setitem(HARNESS_ADAPTERS, DiagnosticHarness.CODEX, _Adapter(sessions))
    first = list_sessions(
        ListRequest(ListHarness.CODEX, repo, tmp_path, tmp_path, tmp_path, limit=10)
    )
    second = list_sessions(
        ListRequest(
            ListHarness.CODEX,
            repo,
            tmp_path,
            tmp_path,
            tmp_path,
            limit=10,
            offset=10,
        )
    )
    assert len(first.sessions) == 10
    assert [item.session_id for item in second.sessions] == ["session-1", "session-0"]


def test_listing_rejects_invalid_limit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(ValueError, match="between 1 and 10"):
        list_sessions(
            ListRequest(ListHarness.CODEX, repo, tmp_path, tmp_path, tmp_path, limit=0)
        )


def test_listing_includes_paseo_worktree_for_its_repo(tmp_path, monkeypatch):
    import subprocess

    from varde_learn.loop.diagnose import list as listing

    repo = tmp_path / "source" / "example"
    repo.mkdir(parents=True)
    subprocess.run(  # noqa: S603 - fixed Git fixture command.
        [  # noqa: S607 - run installed Git against a temporary repository.
            "git",
            "init",
            str(repo),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603 - fixed Git fixture command.
        [  # noqa: S607 - invoke installed Git for the temporary fixture.
            "git",
            "-C",
            str(repo),
            "config",
            "user.email",
            "test@example.com",
        ],
        check=True,
    )
    subprocess.run(  # noqa: S603 - fixed Git fixture command.
        [  # noqa: S607 - invoke installed Git for the temporary fixture.
            "git",
            "-C",
            str(repo),
            "config",
            "user.name",
            "Test",
        ],
        check=True,
    )
    (repo / "tracked.txt").write_text("tracked")
    subprocess.run(  # noqa: S603 - fixed Git fixture command.
        [  # noqa: S607 - invoke installed Git for the temporary fixture.
            "git",
            "-C",
            str(repo),
            "add",
            "tracked.txt",
        ],
        check=True,
    )
    subprocess.run(  # noqa: S603 - fixed Git fixture command.
        [  # noqa: S607 - invoke installed Git for the temporary fixture.
            "git",
            "-C",
            str(repo),
            "commit",
            "-m",
            "initial",
        ],
        check=True,
        capture_output=True,
    )
    paseo_home = tmp_path / ".paseo"
    worktree = paseo_home / "worktrees" / "example"
    worktree.parent.mkdir(parents=True)
    subprocess.run(  # noqa: S603 - fixed Git fixture command.
        [  # noqa: S607 - invoke installed Git for the temporary fixture.
            "git",
            "-C",
            str(repo),
            "worktree",
            "add",
            "--detach",
            str(worktree),
        ],
        check=True,
        capture_output=True,
    )
    session = {
        "harness": "codex",
        "session_id": "worktree-session",
        "identity": "worktree-session",
        "cwd": str(worktree),
    }
    monkeypatch.setattr(listing, "_discover", lambda *args: ([session], []))
    monkeypatch.setattr(listing, "_read_paseo_agents", lambda _: [])
    request = listing.ListRequest(
        "codex",
        repo,
        tmp_path,
        tmp_path,
        tmp_path,
        paseo_home=paseo_home,
    )
    assert listing.list_sessions(request).sessions == []
    request.include_paseo_worktrees = True
    result = listing.list_sessions(request)
    assert [item.session_id for item in result.sessions] == ["worktree-session"]


def test_listing_unknown_run_names_repository_option(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    from varde_learn.loop.diagnose.codex import CodexHarness
    from varde_learn.loop.diagnose.model import HARNESS_ADAPTERS

    register_harness(CodexHarness())
    monkeypatch.setitem(HARNESS_ADAPTERS, DiagnosticHarness.CODEX, _Adapter([]))

    with pytest.raises(ValueError, match="--repository"):
        list_sessions(
            ListRequest(
                ListHarness.CODEX,
                repo,
                tmp_path,
                tmp_path,
                tmp_path,
                run="missing-session",
            )
        )
