#!/usr/bin/env python3
"""Focused regression tests for the efficiency-v3 evidence verifier."""

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("verify-navigation.py")
SKILL_DIR = SCRIPT.parents[1]
SPEC = importlib.util.spec_from_file_location("verify_navigation", SCRIPT)
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


COORDINATOR = """use crate::auth::{session, store};

use crate::auth::session::Session;
use crate::auth::store::TokenStore;

fn fetch_new_access_token() -> String {
    "fresh-access-token".to_owned()
}

pub fn refresh_auth_session(session: &mut Session, store: &mut TokenStore) {
    let token = fetch_new_access_token();
    session::replace_access_token(session, token.clone());
    store::persist_access_token(store, token);
}
"""
SESSION = """#[derive(Default)]
pub struct Session {
    pub access_token: String,
}

pub fn replace_access_token(session: &mut Session, token: String) {
    session.access_token = token;
}
"""
STORE = """#[derive(Default)]
pub struct TokenStore {
    pub saved_access_token: Option<String>,
}

pub fn persist_access_token(store: &mut TokenStore, token: String) {
    store.saved_access_token = Some(token);
}
"""
HELPER = """use crate::auth::refresh_session;

pub fn auth_refresh_helper_21() {
    refresh_session();
}
"""


def event(command, output, phase="item.completed", exit_code=0):
    return {
        "type": "tool_use",
        "name": "command_execution",
        "event_type": phase,
        "input": {
            "event_type": phase,
            "item": {
                "type": "command_execution",
                "command": command,
                "aggregated_output": output,
                "exit_code": exit_code,
            },
        },
    }


def context_output(files, symbols):
    return json.dumps(
        {
            "ok": True,
            "data": {
                "files": [{"path": path, "relevance": "seed"} for path in files],
                "symbols": symbols,
                "tests": [],
                "readingOrder": files,
            },
        }
    )


def symbols_in_files_output(data, ok=True, outcome="success"):
    return json.dumps(
        {
            "ok": ok,
            "outcome": outcome,
            "schema_version": 1,
            "data": data,
            "meta": {"truncated": False},
        }
    )


def get_symbol_output(name, path, source, wrong_span=False, wrong_body=False):
    lines = source.splitlines()
    start, end = VERIFY.function_line_bounds(lines, name)
    body = "\n".join(lines[start - 1 : end])
    if wrong_body:
        body += "\n// unrelated body"
    if wrong_span:
        start += 1
    return json.dumps(
        {
            "ok": True,
            "outcome": "success",
            "schema_version": 1,
            "data": {
                "body": body,
                "file": path,
                "kind": "function",
                "name": name,
                "span": {"start_line": start, "end_line": end},
            },
            "meta": {"compact": True, "truncated": False},
        }
    )


def capture_output(paths):
    return "\n".join(json.dumps({"path": path, "relevance": "seed"}) for path in paths) + "\n"


def declaration(name, path, start, end=None):
    return {
        "name": name,
        "filePath": path,
        "kind": "function",
        "span": {"start_line": start, "end_line": end if end is not None else start},
    }


def case6_evidence():
    symbols = [
        declaration("refresh_auth_session", "src/auth/coordinator.rs", 10, 14),
        declaration("replace_access_token", "src/auth/session.rs", 6, 8),
        declaration("persist_access_token", "src/auth/store.rs", 6, 8),
    ]
    context = context_output([row["filePath"] for row in symbols], symbols)
    body = COORDINATOR[COORDINATOR.index("pub fn refresh_auth_session") :].rstrip()
    body_result = json.dumps(
        {
            "ok": True,
            "data": {
                "name": "refresh_auth_session",
                "file": "src/auth/coordinator.rs",
                "body": body,
                "span": {"start_line": 10, "end_line": 14},
            },
            "meta": {"compact": True, "truncated": False},
        }
    )
    return [
        event("varde-code context_pack --json '{...}'", context),
        event("varde-code get_symbol --json '{...}'", body_result),
    ]


def case6_symbols_in_files_data():
    declarations = (
        ("refresh_auth_session", "src/auth/coordinator.rs", COORDINATOR),
        ("replace_access_token", "src/auth/session.rs", SESSION),
        ("persist_access_token", "src/auth/store.rs", STORE),
    )
    data = {}
    for name, file_path, source in declarations:
        start, end = VERIFY.function_line_bounds(source.splitlines(), name)
        data[file_path] = [
            {
                "file": file_path,
                "kind": "function",
                "name": name,
                "span": {"start_line": start, "end_line": end},
            }
        ]
    return data


def case7_evidence():
    envelope = json.dumps(
        {
            "ok": True,
            "data": {
                "files": [
                    {"path": "src/auth.rs"},
                    {"path": "src/auth_refresh_helper_01.rs"},
                ]
            },
            "meta": {"truncated": True, "toz": {"handle": "capture-abc", "items": 27}},
        }
    )
    occurrence = {
        "name": "refresh_session",
        "filePath": "src/auth_refresh_helper_21.rs",
        "kind": "call",
        "span": {"start_line": 4, "end_line": 4},
    }
    page = context_output(["src/auth_refresh_helper_21.rs"], [occurrence])
    capture_rows = capture_output(
        [f"src/auth_refresh_helper_{number:02}.rs" for number in range(20, 26)] + ["src/lib.rs"]
    )
    return [
        event("cat /sandbox/context-result.json", envelope),
        event(
            "varde-toz query --handle capture-abc --lines 21:27",
            capture_rows,
        ),
        event("varde-code context_pack --json '{\"resultsOffset\":20}'", page),
    ]


CASE6_CORRECT_ANSWER = {
    "readingOrder": [
        {"filePath": "src/auth/coordinator.rs", "span": {"start_line": 10, "end_line": 14}},
        {"filePath": "src/auth/session.rs", "span": {"start_line": 6, "end_line": 8}},
        {"filePath": "src/auth/store.rs", "span": {"start_line": 6, "end_line": 8}},
    ]
}
CASE6_INCORRECT_ANSWER = {
    "readingOrder": [
        {"filePath": "src/auth/store.rs", "span": {"start_line": 6, "end_line": 8}},
        {"filePath": "src/auth/session.rs", "span": {"start_line": 6, "end_line": 8}},
        {"filePath": "src/auth/coordinator.rs", "span": {"start_line": 10, "end_line": 14}},
        {"filePath": "src/metrics.rs", "span": {"start_line": 1, "end_line": 3}},
    ]
}
CASE7_GROUPED_CORRECT_ANSWER = {
    "recoveredFiles": [
        "src/auth_refresh_helper_20.rs",
        "src/auth_refresh_helper_21.rs",
        "src/auth_refresh_helper_22.rs",
        "src/auth_refresh_helper_23.rs",
        "src/auth_refresh_helper_24.rs",
        "src/auth_refresh_helper_25.rs",
        "src/lib.rs",
    ],
    "occurrences": [
        {
            "files": [
                "src/auth_refresh_helper_20.rs",
                "src/auth_refresh_helper_21.rs",
                "src/auth_refresh_helper_22.rs",
                "src/auth_refresh_helper_23.rs",
                "src/auth_refresh_helper_24.rs",
                "src/auth_refresh_helper_25.rs",
            ],
            "kind": "import",
            "span": {"start_line": 1, "end_line": 1},
        },
        {
            "files": [
                "src/auth_refresh_helper_20.rs",
                "src/auth_refresh_helper_21.rs",
                "src/auth_refresh_helper_22.rs",
                "src/auth_refresh_helper_23.rs",
                "src/auth_refresh_helper_24.rs",
                "src/auth_refresh_helper_25.rs",
            ],
            "kind": "call",
            "span": {"start_line": 4, "end_line": 4},
        },
    ],
}
CASE7_INCORRECT_ANSWER = {
    "recoveredFiles": [
        "src/auth_refresh_helper_21.rs",
        "src/auth_refresh_helper_22.rs",
        "src/auth_refresh_helper_23.rs",
        "src/auth_refresh_helper_24.rs",
        "src/auth_refresh_helper_25.rs",
        "src/lib.rs",
    ],
    "occurrences": [
        {
            "files": [
                "src/auth_refresh_helper_21.rs",
                "src/auth_refresh_helper_22.rs",
                "src/auth_refresh_helper_23.rs",
                "src/auth_refresh_helper_24.rs",
                "src/auth_refresh_helper_25.rs",
            ],
            "kind": "call",
            "span": {"start_line": 1, "end_line": 1},
        }
    ],
}
VALID_ANSWERS = {"6": CASE6_CORRECT_ANSWER, "7": CASE7_GROUPED_CORRECT_ANSWER}


def answer_text(answer):
    return json.dumps(answer, separators=(",", ":"))


class NavigationVerifierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name) / "project"
        (self.project / "src/auth").mkdir(parents=True)
        (self.project / "src/auth/coordinator.rs").write_text(COORDINATOR)
        (self.project / "src/auth/session.rs").write_text(SESSION)
        (self.project / "src/auth/store.rs").write_text(STORE)
        (self.project / "src/auth/mod.rs").write_text(
            "pub mod coordinator;\npub mod session;\npub mod store;\n"
        )
        (self.project / "src/auth.rs").write_text(
            "pub fn refresh_session() {\n    record_refresh();\n}\n\nfn record_refresh() {}\n"
        )
        (self.project / "src/metrics.rs").write_text(
            "pub struct MetricsCache;\n\npub fn refresh_metrics_cache() {}\n"
        )
        (self.project / "src/auth_refresh_helper_21.rs").write_text(HELPER)
        (self.project / "src/lib.rs").write_text("pub mod auth;\npub mod metrics;\n")
        for number in range(1, 26):
            if number == 21:
                continue
            (self.project / f"src/auth_refresh_helper_{number:02}.rs").write_text(
                f"use crate::auth::refresh_session;\n\npub fn auth_refresh_helper_{number:02}() {{\n    refresh_session();\n}}\n"
            )

    def tearDown(self):
        self.temp.cleanup()

    def verify(self, case_id, events, transcript=None, load_error=""):
        if transcript is None:
            transcript = answer_text(VALID_ANSWERS[case_id])
        raw = {"messages": [{"content": events}]}
        return VERIFY.verify(
            case_id,
            self.project,
            VERIFY.completed_commands(raw),
            transcript=transcript,
            load_error=load_error,
        )

    def invoke_configured_bash_verifier(self, case_id, events, transcript=None, raw_result=None):
        config = json.loads(SCRIPT.with_name("experimental-navigation.json").read_text())
        eval_config = next(item for item in config["evals"] if str(item["id"]) == case_id)
        script = SKILL_DIR / eval_config["verification_script"]
        run_dir = self.project.parent / f"run-{case_id}"
        outputs_dir = run_dir / "outputs"
        outputs_dir.mkdir(parents=True, exist_ok=True)
        transcript_path = outputs_dir / "transcript.txt"
        if transcript is None:
            transcript = answer_text(VALID_ANSWERS[case_id])
        transcript_path.write_text(transcript)
        (run_dir / "raw.json").write_text(
            json.dumps(
                {
                    "result": transcript if raw_result is None else raw_result,
                    "messages": [{"content": events}],
                }
            )
        )
        environment = os.environ.copy()
        environment.update(
            {
                "EVAL_ID": case_id,
                "EVAL_RUN_DIR": str(run_dir),
                "EVAL_TRANSCRIPT": str(transcript_path),
                "EVAL_SANDBOX_DIR": str(self.project.parent),
                "EVAL_SKILL_DIR": str(SKILL_DIR),
            }
        )
        return subprocess.run(
            ["bash", str(script)],
            cwd=self.project.parent,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    @staticmethod
    def verdicts(results):
        return [item["verdict"] for item in results]

    def test_valid_real_fixture_evidence_passes_for_both_cases(self):
        self.assertEqual(self.verdicts(self.verify("6", case6_evidence())), ["PASS"] * 3)
        self.assertEqual(self.verdicts(self.verify("7", case7_evidence())), ["PASS"] * 3)

    def test_four_independent_final_answer_labels(self):
        fixtures = [
            ("6", case6_evidence(), CASE6_CORRECT_ANSWER, "PASS"),
            ("6", case6_evidence(), CASE6_INCORRECT_ANSWER, "FAIL"),
            ("7", case7_evidence(), CASE7_GROUPED_CORRECT_ANSWER, "PASS"),
            ("7", case7_evidence(), CASE7_INCORRECT_ANSWER, "FAIL"),
        ]
        for case_id, events, answer, final_verdict in fixtures:
            with self.subTest(case_id=case_id, final_verdict=final_verdict):
                results = self.verify(case_id, events, transcript=answer_text(answer))
                self.assertEqual(len(results), 3)
                self.assertEqual(self.verdicts(results[:2]), ["PASS", "PASS"])
                self.assertEqual(self.verdicts(results[2:]), [final_verdict])

    def test_case6_registration_rows_must_cite_module_lines(self):
        answer = json.loads(answer_text(CASE6_CORRECT_ANSWER))
        answer["readingOrder"].insert(
            0,
            {"filePath": "src/auth/mod.rs", "span": {"start_line": 2, "end_line": 2}},
        )
        answer["readingOrder"].append(
            {"filePath": "src/lib.rs", "span": {"start_line": 1, "end_line": 1}}
        )
        valid_subset = self.verify("6", case6_evidence(), answer_text(answer))
        self.assertEqual(self.verdicts(valid_subset), ["PASS"] * 3)

        answer["readingOrder"][0]["span"] = {"start_line": 1, "end_line": 3}
        answer["readingOrder"][-1]["span"] = {"start_line": 1, "end_line": 2}
        valid_whole_files = self.verify("6", case6_evidence(), answer_text(answer))
        self.assertEqual(self.verdicts(valid_whole_files), ["PASS"] * 3)

        answer["readingOrder"][-1]["span"] = {"start_line": 2, "end_line": 2}
        metrics_only = self.verify("6", case6_evidence(), answer_text(answer))
        self.assertEqual(self.verdicts(metrics_only), ["PASS", "PASS", "FAIL"])

        answer["readingOrder"][0]["span"] = {"start_line": 4, "end_line": 4}
        out_of_bounds = self.verify("6", case6_evidence(), answer_text(answer))
        self.assertEqual(self.verdicts(out_of_bounds), ["PASS", "PASS", "FAIL"])

    def test_case6_final_spans_follow_fixture_function_positions(self):
        for path, source in (
            ("src/auth/coordinator.rs", COORDINATOR),
            ("src/auth/session.rs", SESSION),
            ("src/auth/store.rs", STORE),
        ):
            (self.project / path).write_text("\n" + source)
        shifted_answer = {
            "readingOrder": [
                {
                    "filePath": "src/auth/coordinator.rs",
                    "span": {"start_line": 11, "end_line": 15},
                },
                {
                    "filePath": "src/auth/session.rs",
                    "span": {"start_line": 7, "end_line": 9},
                },
                {
                    "filePath": "src/auth/store.rs",
                    "span": {"start_line": 7, "end_line": 9},
                },
            ]
        }
        self.assertTrue(VERIFY.case6_answer_valid(self.project, answer_text(shifted_answer)))
        self.assertFalse(VERIFY.case6_answer_valid(self.project, answer_text(CASE6_CORRECT_ANSWER)))

    def test_case6_final_json_rejects_strict_shape_failures(self):
        row = CASE6_CORRECT_ANSWER["readingOrder"][0]
        extra_key = {"readingOrder": [{**row, "extra": 1}, *CASE6_CORRECT_ANSWER["readingOrder"][1:]]}
        boolean_line = '{"readingOrder":[{"filePath":"src/auth/coordinator.rs","span":{"start_line":true,"end_line":14}}]}'
        duplicate_keys = '{"readingOrder":[],"readingOrder":[]}'
        unknown_root = answer_text({**CASE6_CORRECT_ANSWER, "notes": "extra"})
        prose = answer_text(CASE6_CORRECT_ANSWER) + "\nHere are the files."
        wrong_span = json.loads(answer_text(CASE6_CORRECT_ANSWER))
        wrong_span["readingOrder"][0]["span"]["end_line"] = 15
        invalid_transcripts = [
            "not JSON",
            answer_text(extra_key),
            boolean_line,
            duplicate_keys,
            unknown_root,
            prose,
            answer_text(wrong_span),
            answer_text(CASE6_INCORRECT_ANSWER),
        ]
        for transcript in invalid_transcripts:
            with self.subTest(transcript=transcript):
                results = self.verify("6", case6_evidence(), transcript=transcript)
                self.assertEqual(self.verdicts(results), ["PASS", "PASS", "FAIL"])

    def test_case7_final_json_rejects_strict_shape_and_occurrence_failures(self):
        extra_key = json.loads(answer_text(CASE7_GROUPED_CORRECT_ANSWER))
        extra_key["occurrences"][0]["name"] = "refresh_session"
        boolean_line = json.loads(answer_text(CASE7_GROUPED_CORRECT_ANSWER))
        boolean_line["occurrences"][0]["span"]["start_line"] = True
        empty_group = json.loads(answer_text(CASE7_GROUPED_CORRECT_ANSWER))
        empty_group["occurrences"][0]["files"] = []
        duplicate_tail = json.loads(answer_text(CASE7_GROUPED_CORRECT_ANSWER))
        duplicate_tail["recoveredFiles"].append("src/lib.rs")
        wrong_call_line = json.loads(answer_text(CASE7_GROUPED_CORRECT_ANSWER))
        wrong_call_line["occurrences"][1]["span"] = {"start_line": 1, "end_line": 1}
        declaration_as_call = json.loads(answer_text(CASE7_GROUPED_CORRECT_ANSWER))
        declaration_as_call["occurrences"] = [
            {
                "files": ["src/auth.rs"],
                "kind": "call",
                "span": {"start_line": 1, "end_line": 1},
            }
        ]
        invalid_transcripts = [
            "not JSON",
            '{"recoveredFiles":[],"recoveredFiles":[],"occurrences":[]}',
            answer_text(extra_key),
            answer_text(boolean_line),
            answer_text(empty_group),
            answer_text(duplicate_tail),
            answer_text(wrong_call_line),
            answer_text(declaration_as_call),
            answer_text(CASE7_INCORRECT_ANSWER),
            answer_text({**CASE7_GROUPED_CORRECT_ANSWER, "extra": True}),
            answer_text(CASE7_GROUPED_CORRECT_ANSWER) + " extra prose",
        ]
        for transcript in invalid_transcripts:
            with self.subTest(transcript=transcript):
                results = self.verify("7", case7_evidence(), transcript=transcript)
                self.assertEqual(self.verdicts(results), ["PASS", "PASS", "FAIL"])

    def test_case7_grouped_occurrences_need_not_be_in_recovered_tail(self):
        answer = json.loads(answer_text(CASE7_GROUPED_CORRECT_ANSWER))
        answer["occurrences"] = [
            {
                "files": ["src/auth_refresh_helper_01.rs"],
                "kind": "import",
                "span": {"start_line": 1, "end_line": 1},
            }
        ]
        results = self.verify("7", case7_evidence(), answer_text(answer))
        self.assertEqual(self.verdicts(results), ["PASS"] * 3)

    def test_final_assertion_never_reads_tool_output_as_the_answer(self):
        events = case6_evidence()
        events.append(event("printf final JSON", answer_text(CASE6_INCORRECT_ANSWER)))
        results = self.verify("6", events, transcript=answer_text(CASE6_CORRECT_ANSWER))
        self.assertEqual(self.verdicts(results), ["PASS"] * 3)

    def test_load_error_still_returns_all_three_assertions(self):
        for case_id in ("6", "7"):
            with self.subTest(case_id=case_id):
                results = self.verify(case_id, [], load_error="raw result identity mismatch")
                self.assertEqual(len(results), 3)
                self.assertEqual(self.verdicts(results), ["FAIL"] * 3)

    def test_case6_path_line_text_declarations_and_complete_body_pass(self):
        declarations = "\n".join(
            [
                "project/src/auth/coordinator.rs:10:pub fn refresh_auth_session(session: &mut Session, store: &mut TokenStore) {",
                "project/src/auth/session.rs:6:pub fn replace_access_token(session: &mut Session, token: String) {",
                "project/src/auth/store.rs:6:pub fn persist_access_token(store: &mut TokenStore, token: String) {",
            ]
        )
        events = [
            event("rg -n 'pub fn' ./project/src/auth", declarations),
            event("cat ./project/src/auth/coordinator.rs", COORDINATOR),
        ]
        self.assertEqual(self.verdicts(self.verify("6", events))[:2], ["PASS", "PASS"])

    def test_case6_exact_direct_cat_sources_pass(self):
        events = [
            event(f"cat ./project/src/auth/{name}.rs", source)
            for name, source in (
                ("coordinator", COORDINATOR),
                ("session", SESSION),
                ("store", STORE),
            )
        ]
        self.assertEqual(self.verdicts(self.verify("6", events))[:2], ["PASS", "PASS"])

    def test_case6_three_get_symbol_body_results_pass_without_context_or_source_search(self):
        declarations = (
            ("refresh_auth_session", "src/auth/coordinator.rs", COORDINATOR),
            ("replace_access_token", "src/auth/session.rs", SESSION),
            ("persist_access_token", "src/auth/store.rs", STORE),
        )
        events = [
            event(
                f"varde-code get_symbol {name}",
                get_symbol_output(name, path, source),
            )
            for name, path, source in declarations
        ]
        self.assertEqual(self.verdicts(self.verify("6", events))[:2], ["PASS", "PASS"])

    def test_case6_get_symbol_requires_fixture_matching_span_and_body(self):
        declarations = (
            ("refresh_auth_session", "src/auth/coordinator.rs", COORDINATOR, True),
            ("replace_access_token", "src/auth/session.rs", SESSION, False),
            ("persist_access_token", "src/auth/store.rs", STORE, False),
        )
        events = [
            event(
                f"varde-code get_symbol {name}",
                get_symbol_output(name, path, source, wrong_span=wrong_span),
            )
            for name, path, source, wrong_span in declarations
        ]
        self.assertEqual(self.verdicts(self.verify("6", events))[:2], ["FAIL", "PASS"])

    def test_case6_get_symbol_rejects_wrong_body_even_with_fixture_span(self):
        declarations = (
            ("refresh_auth_session", "src/auth/coordinator.rs", COORDINATOR, True),
            ("replace_access_token", "src/auth/session.rs", SESSION, False),
            ("persist_access_token", "src/auth/store.rs", STORE, False),
        )
        events = [
            event(
                f"varde-code get_symbol {name}",
                get_symbol_output(name, path, source, wrong_body=wrong_body),
            )
            for name, path, source, wrong_body in declarations
        ]
        self.assertEqual(self.verdicts(self.verify("6", events))[:2], ["FAIL", "FAIL"])

    def test_case6_source_declarations_reject_wrong_line_or_text(self):
        rows = [
            "project/src/auth/coordinator.rs:11:pub fn refresh_auth_session(session: &mut Session, store: &mut TokenStore) {",
            "project/src/auth/session.rs:6:pub fn replace_access_token(session: &mut Session, token: String) {",
            "project/src/auth/store.rs:6:pub fn persist_access_token(store: &mut TokenStore, token: String) {",
        ]
        events = [
            event("rg -n 'pub fn' ./project/src/auth", "\n".join(rows)),
        ]
        self.assertEqual(self.verdicts(self.verify("6", events))[0], "FAIL")

    def test_case7_capture_and_path_line_text_occurrence_pass_without_context_pack(self):
        events = case7_evidence()[:2]
        events.append(
            event(
                "rg -n refresh_session ./project/src",
                "project/src/auth_refresh_helper_21.rs:4:    refresh_session();",
            )
        )
        self.assertEqual(self.verdicts(self.verify("7", events))[:2], ["PASS", "PASS"])

    def test_case7_source_import_occurrence_passes(self):
        events = case7_evidence()[:2]
        events.append(
            event(
                "rg -n refresh_session ./project/src",
                "project/src/auth_refresh_helper_21.rs:1:use crate::auth::refresh_session;",
            )
        )
        self.assertEqual(self.verdicts(self.verify("7", events))[:2], ["PASS", "PASS"])

    def test_case7_exact_direct_cat_occurrence_passes(self):
        events = case7_evidence()[:2]
        events.append(event("cat ./project/src/auth_refresh_helper_21.rs", HELPER))
        self.assertEqual(self.verdicts(self.verify("7", events))[:2], ["PASS", "PASS"])

    def test_case7_partial_direct_cat_output_is_not_source_evidence(self):
        events = case7_evidence()[:2]
        events.append(
            event("cat ./project/src/auth_refresh_helper_21.rs", "    refresh_session();\n")
        )
        self.assertEqual(self.verdicts(self.verify("7", events))[:2], ["PASS", "FAIL"])

    def test_case7_handle_prefix_does_not_match_recorded_capture_handle(self):
        events = [
            case7_evidence()[0],
            event(
                "varde-toz query --handle capture-abc-other --lines 21:27",
                capture_output(
                    [f"src/auth_refresh_helper_{number:02}.rs" for number in range(20, 26)]
                    + ["src/lib.rs"]
                ),
            ),
        ]
        self.assertEqual(self.verdicts(self.verify("7", events))[0], "FAIL")

    def test_case7_exact_single_or_double_quoted_capture_handle_passes(self):
        tail = capture_output(
            [f"src/auth_refresh_helper_{number:02}.rs" for number in range(20, 26)]
            + ["src/lib.rs"]
        )
        for quote in ("'", '"'):
            with self.subTest(quote=quote):
                events = [
                    case7_evidence()[0],
                    event(
                        f"varde-toz query --handle {quote}capture-abc{quote} --lines 21:27",
                        tail,
                    ),
                ]
                self.assertEqual(self.verdicts(self.verify("7", events))[0], "PASS")

    def test_case7_source_occurrences_reject_missing_path_or_wrong_source_line(self):
        invalid_rows = [
            "4:    refresh_session();",
            "project/src/auth_refresh_helper_21.rs:5:    refresh_session();",
            "project/src/auth_refresh_helper_21.rs:4:    refresh_sessions();",
            "project/src/metrics.rs:4:    refresh_session();",
        ]
        for row in invalid_rows:
            with self.subTest(row=row):
                events = case7_evidence()[:2]
                events.append(event("rg -n refresh_session ./project/src", row))
                self.assertEqual(self.verdicts(self.verify("7", events))[:2], ["PASS", "FAIL"])

    def test_configured_verifier_succeeds_through_the_bash_runner_for_cases_six_and_seven(self):
        for case_id, events in (("6", case6_evidence()), ("7", case7_evidence())):
            with self.subTest(case_id=case_id):
                config = json.loads(SCRIPT.with_name("experimental-navigation.json").read_text())
                eval_config = next(item for item in config["evals"] if str(item["id"]) == case_id)
                expected = eval_config["assertions"]
                completed = self.invoke_configured_bash_verifier(case_id, events)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                success_results = json.loads(completed.stdout)["results"]
                self.assertEqual([row["assertion"] for row in success_results], expected)
                self.assertEqual(self.verdicts(success_results), ["PASS"] * 3)

                malformed = self.invoke_configured_bash_verifier(
                    case_id, events, transcript="not JSON"
                )
                self.assertEqual(malformed.returncode, 0, malformed.stderr)
                error_results = json.loads(malformed.stdout)["results"]
                self.assertEqual([row["assertion"] for row in error_results], expected)
                self.assertEqual(self.verdicts(error_results), ["PASS", "PASS", "FAIL"])

                incorrect_answer = (
                    CASE6_INCORRECT_ANSWER if case_id == "6" else CASE7_INCORRECT_ANSWER
                )
                incorrect = self.invoke_configured_bash_verifier(
                    case_id, events, transcript=answer_text(incorrect_answer)
                )
                self.assertEqual(incorrect.returncode, 0, incorrect.stderr)
                incorrect_results = json.loads(incorrect.stdout)["results"]
                self.assertEqual([row["assertion"] for row in incorrect_results], expected)
                self.assertEqual(self.verdicts(incorrect_results), ["PASS", "PASS", "FAIL"])

                mismatch = self.invoke_configured_bash_verifier(
                    case_id,
                    events,
                    transcript=answer_text(VALID_ANSWERS[case_id]),
                    raw_result="different result string",
                )
                self.assertEqual(mismatch.returncode, 0, mismatch.stderr)
                mismatch_results = json.loads(mismatch.stdout)["results"]
                self.assertEqual([row["assertion"] for row in mismatch_results], expected)
                self.assertEqual(self.verdicts(mismatch_results), ["FAIL"] * 3)

    def test_case6_symbols_in_files_adapter_through_configured_bash_runner(self):
        data = case6_symbols_in_files_data()
        batch_command = "varde-code symbols_in_files --json '{...}'"
        body_command = "varde-code get_symbol refresh_auth_session"
        body_output = get_symbol_output(
            "refresh_auth_session", "src/auth/coordinator.rs", COORDINATOR
        )

        def run_batch(batch_event):
            completed = self.invoke_configured_bash_verifier(
                "6",
                [batch_event, event(body_command, body_output)],
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            return json.loads(completed.stdout)["results"]

        successful = run_batch(event(batch_command, symbols_in_files_output(data)))
        self.assertEqual(self.verdicts(successful), ["PASS"] * 3)

        session_path = "src/auth/session.rs"

        def changed_session(**changes):
            return {
                **data,
                session_path: [{**data[session_path][0], **changes}],
            }

        def batch_event(payload, *, ok=True, outcome="success", phase="item.completed", exit_code=0):
            return event(
                batch_command,
                symbols_in_files_output(payload, ok=ok, outcome=outcome),
                phase,
                exit_code,
            )

        invalid_batches = [
            (
                "per-file errors do not count as symbol rows",
                batch_event({**data, session_path: {"error": {"code": "not_found"}}}),
            ),
            (
                "row file must match its map key",
                batch_event(changed_session(file="src/auth/coordinator.rs")),
            ),
            (
                "declaration name must match the fixture",
                batch_event(changed_session(name="refresh_metrics_cache")),
            ),
            (
                "declaration kind must be a function",
                batch_event(changed_session(kind="call")),
            ),
            (
                "declaration span must match source",
                batch_event(changed_session(span={"start_line": 7, "end_line": 8})),
            ),
            (
                "outer failure envelope is ignored",
                batch_event(data, ok=False),
            ),
            (
                "non-success outcome is ignored",
                batch_event(data, outcome="error"),
            ),
            (
                "updated lifecycle events are not completed evidence",
                batch_event(data, phase="item.updated"),
            ),
            (
                "nonzero command exit is not evidence",
                batch_event(data, exit_code=1),
            ),
        ]
        for label, batch in invalid_batches:
            with self.subTest(label=label):
                failed = run_batch(batch)
                self.assertEqual(self.verdicts(failed), ["FAIL", "PASS", "PASS"])

    def test_started_and_updated_outputs_are_not_completed_evidence(self):
        symbols = [
            declaration("refresh_auth_session", "src/auth/coordinator.rs", 10, 14),
            declaration("replace_access_token", "src/auth/session.rs", 6, 8),
            declaration("persist_access_token", "src/auth/store.rs", 6, 8),
        ]
        context = context_output(
            ["src/auth/coordinator.rs", "src/auth/session.rs", "src/auth/store.rs"], symbols
        )
        events = [
            event("varde-code context_pack --json", context, "item.started"),
            event("varde-code context_pack --json", context, "item.updated"),
            event("varde-code context_pack --json", "", "item.completed"),
        ]
        self.assertEqual(self.verdicts(self.verify("6", events))[0], "FAIL")

    def test_requested_flags_without_returned_results_do_not_pass(self):
        events = [
            event(
                "varde-code context_pack --json '{\"includeOccurrences\":true,\"fullResults\":true}'",
                "query started",
            )
        ]
        self.assertEqual(self.verdicts(self.verify("6", events))[0], "FAIL")
        self.assertEqual(self.verdicts(self.verify("7", events))[0], "FAIL")

    def test_nonzero_completed_command_cannot_supply_evidence(self):
        events = case6_evidence()
        item = events[0]["input"]["item"]
        events[0] = event(item["command"], item["aggregated_output"], exit_code=1)
        self.assertEqual(self.verdicts(self.verify("6", events))[0], "FAIL")

    def test_missing_source_body_fails_even_with_valid_context_spans(self):
        self.assertEqual(self.verdicts(self.verify("6", case6_evidence()[:1]))[:2], ["PASS", "FAIL"])

    def test_partial_or_scattered_body_lines_do_not_count_as_inspection(self):
        events = case6_evidence()[:1]
        partial = "pub fn refresh_auth_session(session: &mut Session, store: &mut TokenStore) {\n"
        partial += "    session::replace_access_token(session, token.clone());\n"
        partial += "    store::persist_access_token(store, token);\n"
        events.append(event("rg refresh_auth_session src/auth/coordinator.rs", partial))
        self.assertEqual(self.verdicts(self.verify("6", events))[1], "FAIL")

    def test_plain_source_output_counts_as_body_inspection(self):
        events = case6_evidence()[:1]
        events.append(event("sed -n '1,20p' src/auth/coordinator.rs", COORDINATOR))
        self.assertEqual(self.verdicts(self.verify("6", events))[1], "PASS")

    def test_wrong_declaration_span_fails(self):
        events = case6_evidence()
        wrong = [
            declaration("refresh_auth_session", "src/auth/coordinator.rs", 1, 14),
            declaration("replace_access_token", "src/auth/session.rs", 6, 8),
            declaration("persist_access_token", "src/auth/store.rs", 6, 8),
        ]
        events[0] = event(
            "varde-code context_pack --json",
            context_output(
                ["src/auth/coordinator.rs", "src/auth/session.rs", "src/auth/store.rs"], wrong
            ),
        )
        self.assertEqual(self.verdicts(self.verify("6", events))[0], "FAIL")

    def test_declarations_split_across_successful_context_envelopes_pass(self):
        symbols = [
            declaration("refresh_auth_session", "src/auth/coordinator.rs", 10, 14),
            declaration("replace_access_token", "src/auth/session.rs", 6, 8),
            declaration("persist_access_token", "src/auth/store.rs", 6, 8),
        ]
        events = case6_evidence()[1:]
        events[:0] = [
            event(
                "varde-code context_pack --json",
                context_output(
                    ["src/auth/coordinator.rs", "src/auth/session.rs"], symbols[:2]
                ),
            ),
            event(
                "varde-code context_pack --json",
                context_output(["src/auth/store.rs"], symbols[2:]),
            ),
        ]
        self.assertEqual(self.verdicts(self.verify("6", events))[0], "PASS")

    def test_missing_capture_file_output_fails_recovery(self):
        self.assertEqual(self.verdicts(self.verify("7", case7_evidence()[1:]))[0], "FAIL")

    def test_partial_capture_tail_fails_recovery(self):
        events = case7_evidence()
        item = events[1]["input"]["item"]
        output = item["aggregated_output"].replace(
            json.dumps({"path": "src/lib.rs", "relevance": "seed"}) + "\n", ""
        )
        events[1] = event(item["command"], output)
        self.assertEqual(self.verdicts(self.verify("7", events))[0], "FAIL")

    def test_capture_tail_can_be_recovered_in_chunks_for_the_same_handle(self):
        events = case7_evidence()
        first = [f"src/auth_refresh_helper_{number:02}.rs" for number in range(20, 23)]
        second = [f"src/auth_refresh_helper_{number:02}.rs" for number in range(23, 26)] + ["src/lib.rs"]
        events[1:2] = [
            event("varde-toz query --handle capture-abc --lines 21:23", capture_output(first)),
            event("varde-toz query --handle capture-abc --lines 24:27", capture_output(second)),
        ]
        self.assertEqual(self.verdicts(self.verify("7", events))[0], "PASS")

    def test_redundant_later_envelope_and_capture_reread_do_not_hide_first_recovery(self):
        events = case7_evidence()
        envelope = events[0]["input"]["item"]["aggregated_output"]
        capture = events[1]["input"]["item"]["aggregated_output"]
        events.extend(
            [
                event("cat /sandbox/context-result.json", envelope),
                event("varde-toz query --handle capture-abc --lines 21:27", capture),
            ]
        )
        self.assertEqual(self.verdicts(self.verify("7", events))[0], "PASS")

    def test_replacement_paging_before_capture_recovery_fails(self):
        events = case7_evidence()
        events[1], events[2] = events[2], events[1]
        self.assertEqual(self.verdicts(self.verify("7", events))[0], "FAIL")

    def test_batched_capture_and_page_without_observable_order_fails(self):
        events = case7_evidence()[:1]
        events.append(
            event(
                "varde-toz query --handle capture-abc; varde-code context_pack --json '{\"resultsOffset\":20}'",
                "src/auth_refresh_helper_21.rs\n" + context_output(
                    ["src/auth_refresh_helper_21.rs"],
                    [
                        {
                            "name": "refresh_session",
                            "filePath": "src/auth_refresh_helper_21.rs",
                            "kind": "call",
                            "span": {"start_line": 4, "end_line": 4},
                        }
                    ],
                ),
            )
        )
        self.assertEqual(self.verdicts(self.verify("7", events))[0], "FAIL")

    def test_wrong_occurrence_span_fails(self):
        events = case7_evidence()
        output = json.loads(events[2]["input"]["item"]["aggregated_output"])
        output["data"]["symbols"][0]["span"] = {"start_line": 1, "end_line": 4}
        events[2] = event("varde-code context_pack --json", json.dumps(output))
        self.assertEqual(self.verdicts(self.verify("7", events))[1], "FAIL")


if __name__ == "__main__":
    unittest.main()
