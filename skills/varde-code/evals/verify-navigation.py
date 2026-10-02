#!/usr/bin/env python3
"""Verify observable navigation evidence for efficiency-v3 cases 6 and 7."""

import json
import os
import re
from pathlib import Path


ASSERTIONS = {
    "6": [
        "Uses indexed or source declaration evidence with fixture-verified spans",
        "Inspects the auth coordinator body from actual source evidence",
        "Final JSON orders the auth coordinator, session, and store with exact fixture spans, allowing only useful auth module files",
    ],
    "7": [
        "Reads the supplied capture envelope and recovers the complete later-file tail from its recorded handle",
        "Returns actual matching occurrences with source-verified spans",
        "Final JSON lists the complete recovered tail and source-valid refresh_session occurrence groups",
    ],
}
DECLARATION_KINDS = {"function", "class", "interface", "variable", "export", "route"}
OCCURRENCE_KINDS = {"call", "import"}
AUTH_DECLARATIONS = {
    "refresh_auth_session": "src/auth/coordinator.rs",
    "replace_access_token": "src/auth/session.rs",
    "persist_access_token": "src/auth/store.rs",
}
CAPTURE_TAIL_ROWS = {"src/lib.rs"} | {
    f"src/auth_refresh_helper_{number:02}.rs" for number in range(20, 26)
}
MODULE_REGISTRATION_FILES = {"src/auth/mod.rs", "src/lib.rs"}


def json_values(text):
    """Decode JSON values embedded in command output without parsing shell syntax."""
    decoder = json.JSONDecoder()
    values = []
    cursor = 0
    while cursor < len(text):
        start = min(
            (pos for pos in (text.find("{", cursor), text.find("[", cursor)) if pos >= 0),
            default=-1,
        )
        if start < 0:
            break
        try:
            value, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            cursor = start + 1
            continue
        values.append(value)
        cursor = end
    return values


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def completed_commands(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get("messages"), list):
        return []
    commands = []
    for message in raw.get("messages", []):
        if not isinstance(message, dict) or not isinstance(message.get("content"), list):
            continue
        for block in message.get("content", []):
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use" or block.get("name") != "command_execution":
                continue
            inputs = block.get("input", {})
            if not isinstance(inputs, dict):
                continue
            event_type = block.get("event_type") or inputs.get("event_type")
            item = inputs.get("item", {})
            if (
                event_type != "item.completed"
                or not isinstance(item, dict)
                or item.get("type") != "command_execution"
                or item.get("exit_code") != 0
            ):
                continue
            command = item.get("command")
            output = item.get("aggregated_output")
            if not isinstance(command, str) or not isinstance(output, str):
                continue
            commands.append(
                {
                    "command": command,
                    "output": output,
                }
            )
    return commands


def load_run():
    run_dir = Path(os.environ.get("EVAL_RUN_DIR", ""))
    sandbox = Path(os.environ.get("EVAL_SANDBOX_DIR", ""))
    try:
        raw = json.loads((run_dir / "raw.json").read_text())
        transcript = Path(os.environ["EVAL_TRANSCRIPT"]).read_text()
    except (KeyError, OSError, json.JSONDecodeError) as error:
        return sandbox / "project", [], "", f"run evidence unavailable: {error}"
    if not isinstance(raw, dict):
        return sandbox / "project", [], "", "raw.json has an unsupported top-level shape"
    if raw.get("result") != transcript:
        return sandbox / "project", [], "", "raw.json and EVAL_TRANSCRIPT do not describe the same run"
    return sandbox / "project", completed_commands(raw), transcript, ""


def successful_context_outputs(commands):
    outputs = []
    for index, command in enumerate(commands):
        if "varde-code" not in command["command"] or "context_pack" not in command["command"]:
            continue
        for value in json_values(command["output"]):
            if isinstance(value, dict) and value.get("ok") is True and isinstance(value.get("data"), dict):
                outputs.append((index, value))
    return outputs


def successful_symbols_in_files_outputs(commands):
    outputs = []
    for index, command in enumerate(commands):
        if "varde-code" not in command["command"] or "symbols_in_files" not in command["command"]:
            continue
        for value in json_values(command["output"]):
            if (
                isinstance(value, dict)
                and value.get("ok") is True
                and value.get("outcome") == "success"
                and isinstance(value.get("data"), dict)
            ):
                outputs.append((index, value))
    return outputs


def successful_get_symbol_outputs(commands):
    outputs = []
    for index, command in enumerate(commands):
        if "varde-code" not in command["command"] or "get_symbol" not in command["command"]:
            continue
        for value in json_values(command["output"]):
            if (
                isinstance(value, dict)
                and value.get("ok") is True
                and value.get("outcome") == "success"
                and isinstance(value.get("data"), dict)
            ):
                outputs.append((index, value))
    return outputs


def source_lines(project, file_path):
    try:
        root = project.resolve()
        path = (root / file_path).resolve()
        if root not in path.parents:
            return None
        return path.read_text().splitlines()
    except (OSError, TypeError, ValueError):
        return None


def source_path_from_output(project, output_path):
    root = project.resolve()
    path = Path(output_path)
    if path.is_absolute():
        try:
            relative = path.resolve().relative_to(root).as_posix()
        except ValueError:
            return None
    else:
        relative = output_path.removeprefix("./")
        if relative.startswith("project/"):
            relative = relative.removeprefix("project/")
    return relative if relative.startswith("src/") else None


def direct_cat_rows(project, command):
    match = re.fullmatch(
        r"\s*cat\s+(?:--\s+)?(?:'([^']+)'|\"([^\"]+)\"|([^\s]+))\s*",
        command["command"],
    )
    if match is None:
        return set()
    output_path = next(value for value in match.groups() if value is not None)
    file_path = source_path_from_output(project, output_path)
    lines = source_lines(project, file_path) if file_path is not None else None
    if lines is None:
        return set()
    try:
        expected = (project / file_path).resolve().read_text()
    except OSError:
        return set()
    if command["output"].replace("\r\n", "\n") != expected.replace("\r\n", "\n"):
        return set()
    return {(file_path, number, line) for number, line in enumerate(lines, start=1)}


def source_match_rows(project, commands):
    rows = set()
    line_pattern = re.compile(r"^(.+?):([1-9]\d*):(.*)$")
    cached_lines = {}
    for command in commands:
        rows.update(direct_cat_rows(project, command))
        for output_line in command["output"].splitlines():
            match = line_pattern.fullmatch(output_line)
            if match is None:
                continue
            file_path = source_path_from_output(project, match.group(1))
            if file_path is None:
                continue
            if file_path not in cached_lines:
                cached_lines[file_path] = source_lines(project, file_path)
            lines = cached_lines[file_path]
            line_number = int(match.group(2))
            text = match.group(3)
            if lines is not None and line_number <= len(lines) and lines[line_number - 1] == text:
                rows.add((file_path, line_number, text))
    return rows


def valid_declaration_span(project, row, name, expected_path):
    if row.get("name") != name or row.get("filePath") != expected_path:
        return False
    span = row.get("span", {})
    if not isinstance(span, dict):
        return False
    start = span.get("start_line")
    end = span.get("end_line")
    lines = source_lines(project, expected_path)
    if lines is None or not isinstance(start, int) or not isinstance(end, int):
        return False
    return (start, end) == function_line_bounds(lines, name)


def function_line_bounds(lines, name):
    for start_index, line in enumerate(lines):
        if re.search(r"\bfn\s+" + re.escape(name) + r"\b", line) is None:
            continue
        depth = 0
        opened = False
        for end_index in range(start_index, len(lines)):
            for char in lines[end_index]:
                if char == "{":
                    depth += 1
                    opened = True
                elif char == "}":
                    depth -= 1
                    if opened and depth == 0:
                        return start_index + 1, end_index + 1
        return None
    return None


def get_symbol_declaration_verified(project, outputs, name, file_path):
    lines = source_lines(project, file_path)
    bounds = function_line_bounds(lines, name) if lines is not None else None
    if bounds is None:
        return False
    expected_body = "\n".join(lines[bounds[0] - 1 : bounds[1]])
    for _, envelope in outputs:
        data = envelope["data"]
        span = data.get("span")
        if (
            data.get("name") == name
            and data.get("file") == file_path
            and data.get("kind") in DECLARATION_KINDS
            and isinstance(span, dict)
            and (span.get("start_line"), span.get("end_line")) == bounds
            and data.get("body") == expected_body
        ):
            return True
    return False


def source_declaration_verified(project, source_rows, name, file_path):
    lines = source_lines(project, file_path)
    bounds = function_line_bounds(lines, name) if lines is not None else None
    if bounds is None:
        return False
    line_number = bounds[0]
    return (file_path, line_number, lines[line_number - 1]) in source_rows


def auth_context_verified(project, context_outputs, commands):
    files = set()
    rows = []
    source_rows = source_match_rows(project, commands)
    symbol_file_outputs = successful_symbols_in_files_outputs(commands)
    symbol_outputs = successful_get_symbol_outputs(commands)
    for _, envelope in context_outputs:
        data = envelope["data"]
        if not isinstance(data.get("files"), list) or not isinstance(data.get("symbols"), list):
            continue
        files.update(
            row.get("path")
            for row in data["files"]
            if isinstance(row, dict) and isinstance(row.get("path"), str)
        )
        rows.extend(row for row in data["symbols"] if isinstance(row, dict))
    for _, envelope in symbol_file_outputs:
        for file_path, entries in envelope["data"].items():
            if not isinstance(file_path, str) or not isinstance(entries, list):
                continue
            files.add(file_path)
            for row in entries:
                if (
                    not isinstance(row, dict)
                    or row.get("file") != file_path
                    or row.get("kind") != "function"
                    or AUTH_DECLARATIONS.get(row.get("name")) != file_path
                ):
                    continue
                normalized = dict(row, filePath=file_path)
                if valid_declaration_span(project, normalized, row["name"], file_path):
                    rows.append(normalized)
    for name, file_path in AUTH_DECLARATIONS.items():
        symbol_file_seen = any(
            envelope["data"].get("name") == name
            and envelope["data"].get("file") == file_path
            for _, envelope in symbol_outputs
        )
        file_seen = (
            file_path in files
            or any(path == file_path for path, _, _ in source_rows)
            or symbol_file_seen
        )
        declaration_seen = any(
            row.get("name") == name
            and row.get("filePath") == file_path
            and row.get("kind") in DECLARATION_KINDS
            and valid_declaration_span(project, row, name, file_path)
            for row in rows
        ) or source_declaration_verified(project, source_rows, name, file_path) or (
            get_symbol_declaration_verified(project, symbol_outputs, name, file_path)
        )
        if not file_seen or not declaration_seen:
            return False
    return True


def coordinator_body(project):
    lines = source_lines(project, "src/auth/coordinator.rs")
    if lines is None:
        return None
    bounds = function_line_bounds(lines, "refresh_auth_session")
    if bounds is None:
        return None
    return "\n".join(lines[bounds[0] - 1 : bounds[1]])


def body_was_inspected(project, commands):
    expected_body = coordinator_body(project)
    if not expected_body:
        return False
    expected_lines = [
        line.strip()
        for line in expected_body.splitlines()
        if line.strip()
    ]
    for command in commands:
        output = command["output"].replace("\r\n", "\n")
        if expected_body in output:
            return True
        output_lines = [
            re.sub(r"^\s*\d+\s*(?:\||:)?\s*", "", line).strip()
            for line in output.splitlines()
        ]
        width = len(expected_lines)
        if width and any(output_lines[start : start + width] == expected_lines for start in range(len(output_lines))):
            return True
        for value in json_values(output):
            if not isinstance(value, dict) or value.get("ok") is not True:
                continue
            for row in walk(value):
                if (
                    row.get("name") == "refresh_auth_session"
                    and row.get("file") == "src/auth/coordinator.rs"
                    and row.get("body") == expected_body
                ):
                    return True
    return False


def capture_envelopes(commands):
    found = []
    for index, command in enumerate(commands):
        if "context-result.json" not in command["command"]:
            continue
        for value in json_values(command["output"]):
            if not isinstance(value, dict) or value.get("ok") is not True:
                continue
            meta = value.get("meta")
            if not isinstance(meta, dict) or not isinstance(meta.get("toz"), dict):
                continue
            toz = meta["toz"]
            handle = toz.get("handle")
            items = toz.get("items")
            if meta.get("truncated") is True and isinstance(handle, str) and handle:
                if isinstance(items, int) and items > 20:
                    found.append((index, handle))
    return found


def command_uses_capture_handle(command, handle):
    escaped_handle = re.escape(handle)
    pattern = (
        rf"(?:^|\s)--handle\s+(?:{escaped_handle}|"
        rf"'{escaped_handle}'|\"{escaped_handle}\")(?=$|\s)"
    )
    return re.search(pattern, command) is not None


def capture_rows_after_20(commands, envelopes):
    recovered = []
    for envelope_index, handle in envelopes:
        rows = set()
        first_complete_index = None
        for index, command in enumerate(commands):
            if index <= envelope_index:
                continue
            if "varde-toz query" not in command["command"] or not command_uses_capture_handle(
                command["command"], handle
            ):
                continue
            found = {
                value.get("path")
                for value in json_values(command["output"])
                if isinstance(value, dict) and value.get("path") in CAPTURE_TAIL_ROWS
            }
            if found:
                rows.update(found)
                if first_complete_index is None and CAPTURE_TAIL_ROWS <= rows:
                    first_complete_index = index
        if first_complete_index is not None:
            recovered.append((first_complete_index, handle, rows))
    return recovered


def is_file_paging(command):
    text = command["command"]
    if "varde-code" not in text or "context_pack" not in text or "resultsOffset" not in text:
        return False
    return re.search(r"resultsOffset.{0,16}(?:2[0-9]|[3-9][0-9]|[1-9][0-9]{2,})\b", text) is not None


def occurrence_span_valid(project, row):
    name = row.get("name")
    file_path = row.get("filePath")
    kind = row.get("kind")
    if name != "refresh_session" or kind not in OCCURRENCE_KINDS:
        return False
    if not isinstance(file_path, str) or re.fullmatch(r"src/auth_refresh_helper_\d{2}\.rs", file_path) is None:
        return False
    span = row.get("span", {})
    if not isinstance(span, dict):
        return False
    start, end = span.get("start_line"), span.get("end_line")
    lines = source_lines(project, file_path)
    if lines is None or not isinstance(start, int) or not isinstance(end, int):
        return False
    pattern = r"\brefresh_session\s*\(" if kind == "call" else r"\buse\b.*\brefresh_session\b"
    expected = [(index, index) for index, line in enumerate(lines, start=1) if re.search(pattern, line)]
    return (start, end) in expected


def source_occurrence_verified(project, source_rows):
    for file_path, _, text in source_rows:
        if re.fullmatch(r"src/auth_refresh_helper_\d{2}\.rs", file_path) is None:
            continue
        if re.search(r"\brefresh_session\s*\(", text) or re.search(
            r"\buse\b.*\brefresh_session\b", text
        ):
            return True
    return False


def occurrence_verified(project, context_outputs, commands):
    for _, envelope in context_outputs:
        for row in envelope["data"].get("symbols", []):
            if isinstance(row, dict) and occurrence_span_valid(project, row):
                return True
    return source_occurrence_verified(project, source_match_rows(project, commands))


def strict_json_object(text):
    def unique_keys(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = item
        return value

    def reject_constant(token):
        raise ValueError(f"invalid JSON constant: {token}")

    value = json.loads(text, object_pairs_hook=unique_keys, parse_constant=reject_constant)
    return value if isinstance(value, dict) else None


def answer_span(value, expected):
    return (
        isinstance(value, dict)
        and set(value) == {"start_line", "end_line"}
        and type(value["start_line"]) is int
        and type(value["end_line"]) is int
        and (value["start_line"], value["end_line"]) == expected
    )


def case6_answer_valid(project, transcript):
    try:
        answer = strict_json_object(transcript)
        if answer is None or set(answer) != {"readingOrder"}:
            return False
        rows = answer["readingOrder"]
        if not isinstance(rows, list):
            return False
        paths = []
        core = []
        core_paths = list(AUTH_DECLARATIONS.values())
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"filePath", "span"}:
                return False
            path = row["filePath"]
            if not isinstance(path, str) or path in paths:
                return False
            paths.append(path)
            function = next(
                (name for name, file_path in AUTH_DECLARATIONS.items() if file_path == path),
                None,
            )
            if function is not None:
                lines = source_lines(project, path)
                bounds = function_line_bounds(lines, function) if lines is not None else None
                if bounds is None or not answer_span(row["span"], bounds):
                    return False
                core.append(path)
                continue
            if path not in MODULE_REGISTRATION_FILES:
                return False
            lines = source_lines(project, path)
            span = row["span"]
            if lines is None or not isinstance(span, dict) or set(span) != {"start_line", "end_line"}:
                return False
            start, end = span["start_line"], span["end_line"]
            if type(start) is not int or type(end) is not int or start < 1 or end < start or end > len(lines):
                return False
            module_names = set()
            for line in lines[start - 1 : end]:
                match = re.fullmatch(r"\s*(?:pub\s+)?mod\s+([A-Za-z_]\w*);\s*", line)
                if match is not None:
                    module_names.add(match.group(1))
            if not module_names or (path == "src/lib.rs" and "auth" not in module_names):
                return False
        return core == core_paths
    except (json.JSONDecodeError, ValueError, TypeError):
        return False


def case7_answer_valid(project, transcript):
    try:
        answer = strict_json_object(transcript)
        if answer is None or set(answer) != {"recoveredFiles", "occurrences"}:
            return False
        recovered = answer["recoveredFiles"]
        groups = answer["occurrences"]
        if (
            not isinstance(recovered, list)
            or any(not isinstance(path, str) for path in recovered)
            or len(recovered) != len(set(recovered))
            or set(recovered) != CAPTURE_TAIL_ROWS
            or not isinstance(groups, list)
            or not groups
        ):
            return False
        for group in groups:
            if not isinstance(group, dict) or set(group) != {"files", "kind", "span"}:
                return False
            files, kind, span = group["files"], group["kind"], group["span"]
            if (
                not isinstance(files, list)
                or not files
                or kind not in OCCURRENCE_KINDS
                or not isinstance(span, dict)
                or set(span) != {"start_line", "end_line"}
                or type(span["start_line"]) is not int
                or type(span["end_line"]) is not int
            ):
                return False
            for path in files:
                if not isinstance(path, str) or not occurrence_span_valid(
                    project,
                    {"name": "refresh_session", "filePath": path, "kind": kind, "span": span},
                ):
                    return False
        return True
    except (json.JSONDecodeError, ValueError, TypeError):
        return False


def recovery_verified(commands):
    envelopes = capture_envelopes(commands)
    recovered = capture_rows_after_20(commands, envelopes)
    if not recovered:
        return False, "no completed capture query returned matching helper rows after offset 20"
    page_indexes = [index for index, command in enumerate(commands) if is_file_paging(command)]
    first_recovery = min(index for index, _, _ in recovered)
    if page_indexes and min(page_indexes) <= first_recovery:
        return False, "capture-before-paging order is missing or a file page completed first"
    return True, "recorded capture handle was read; completed output contained the full later-file tail"


def result(assertion, passed, evidence):
    return {
        "assertion": assertion,
        "verdict": "PASS" if passed else "FAIL",
        "evidence": evidence,
    }


def verify(case_id, project, commands, transcript="", load_error=""):
    context_outputs = successful_context_outputs(commands)
    if case_id == "6":
        context_pass = not load_error and auth_context_verified(project, context_outputs, commands)
        body_pass = not load_error and body_was_inspected(project, commands)
        final_pass = not load_error and case6_answer_valid(project, transcript)
        return [
            result(
                ASSERTIONS["6"][0],
                context_pass,
                "indexed or path/line/text declaration evidence matched fixture source"
                if context_pass
                else load_error or "missing successful auth declarations or source-matching line spans",
            ),
            result(
                ASSERTIONS["6"][1],
                body_pass,
                "coordinator body appeared in completed source output"
                if body_pass
                else load_error or "coordinator body was not present in completed source output",
            ),
            result(
                ASSERTIONS["6"][2],
                final_pass,
                "final JSON matches the auth fixture reading order"
                if final_pass
                else load_error or "final JSON is malformed or does not match the fixture contract",
            ),
        ]
    if case_id == "7":
        recovered, evidence = recovery_verified(commands)
        occurrence_pass = not load_error and occurrence_verified(project, context_outputs, commands)
        final_pass = not load_error and case7_answer_valid(project, transcript)
        return [
            result(ASSERTIONS["7"][0], not load_error and recovered, load_error or evidence),
            result(
                ASSERTIONS["7"][1],
                occurrence_pass,
                "indexed occurrence span or source path/line/text matched fixture source"
                if occurrence_pass
                else load_error or "no indexed occurrence span or source-verified path/line/text",
            ),
            result(
                ASSERTIONS["7"][2],
                final_pass,
                "final JSON matches the recovered tail and source occurrence fixture"
                if final_pass
                else load_error or "final JSON is malformed or does not match the fixture contract",
            ),
        ]
    raise ValueError(f"unsupported efficiency-v3 eval id: {case_id}")


def main():
    case_id = os.environ.get("EVAL_ID", "")
    project, commands, transcript, load_error = load_run()
    try:
        results = verify(case_id, project, commands, transcript, load_error)
    except (OSError, ValueError, TypeError, KeyError) as error:
        results = [
            {"assertion": assertion, "verdict": "FAIL", "evidence": f"verification evidence unavailable: {error}"}
            for assertion in ASSERTIONS.get(case_id, [])
        ]
    print(json.dumps({"results": results}, separators=(",", ":")))


if __name__ == "__main__":
    main()
