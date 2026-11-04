from varde_code.extract import extract_file
from varde_code.extract.langs import tables_for
from varde_code.model import EntityKind


def test_each_language_has_its_own_tree_sitter_table():
    for language in ("javascript", "typescript", "tsx"):
        module_name = "ts" if language == "typescript" else language
        module = __import__(
            f"varde_code.extract.langs.{module_name}", fromlist=["LANG"]
        )
        assert module.BACKEND == "tree-sitter"
        assert tables_for(language) is module.LANG


def test_javascript_extracts_common_entities():
    output = extract_file(
        "sample.js",
        (
            'import x from "./x"; export function run(a = 1) { '
            "const value = x(a); if (value) return value.name; "
            'throw new Error("bad"); }'
        ),
        "javascript",
    )
    pairs = {(entity.kind, entity.name) for entity in output.entities}
    assert (EntityKind.IMPORT, "./x") in pairs
    assert (EntityKind.EXPORT, "run") in pairs
    assert (EntityKind.FUNCTION, "run") in pairs
    assert (EntityKind.PARAMETER, "a") in pairs
    assert (EntityKind.CALL, "x") in pairs
    assert (EntityKind.MEMBER_ACCESS, "name") in pairs
    assert (EntityKind.THROW, 'new Error("bad")') in pairs


def test_typescript_and_tsx_keep_type_declarations_and_ignore_type_literals():
    source = (
        "interface Shape { size: number } export class Box { "
        'value: string = "x"; get(n: number): string { return this.value; } }'
    )
    for language, path in (("typescript", "sample.ts"), ("tsx", "sample.tsx")):
        output = extract_file(path, source, language)
        pairs = {(entity.kind, entity.name) for entity in output.entities}
        assert (EntityKind.INTERFACE, "Shape") in pairs
        assert (EntityKind.CLASS, "Box") in pairs
        assert (EntityKind.FUNCTION, "get") in pairs
        assert (EntityKind.VARIABLE, "value") in pairs
        assert (EntityKind.LITERAL, '"x"') in pairs
        assert not any(
            entity.kind == EntityKind.LITERAL and entity.name == "number"
            for entity in output.entities
        )


def test_tsx_extracts_script_entities_inside_jsx():
    output = extract_file(
        "View.tsx",
        "function View({ value }: Props) { return <button>{send(value)}</button>; }",
        "tsx",
    )
    pairs = {(entity.kind, entity.name) for entity in output.entities}
    assert (EntityKind.FUNCTION, "View") in pairs
    assert (EntityKind.CALL, "send") in pairs
    assert (EntityKind.PARAMETER, "{ value }") in pairs


def test_typescript_destructured_parameter_keeps_its_source_name():
    output = extract_file(
        "sample.ts", "function load({ repoId }: Options) {}", "typescript"
    )
    parameters = [
        entity.name for entity in output.entities if entity.kind == EntityKind.PARAMETER
    ]
    assert parameters == ["{ repoId }"]
