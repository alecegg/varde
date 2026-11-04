from varde_code.quality_pass.facts import extract_facts


def test_typescript_parameters_exports_and_overloads():
    facts = extract_facts(
        (
            "export const mapValues = ({value}: Input, ...rest: string[]) => "
            "rest.map(x => x);\n"
            "function unusedFunction(value: number): number { return value; }\n"
            "function usedFunction(): number { return 1; }\n"
            "export function caller(): number { return usedFunction(); }\n"
            "export function convert(value: string): string;\n"
            "export function convert(value: number): number;\n"
            "export function convert(value) { return value; }\n"
        ),
        "typescript",
    )
    rows = facts["functions"]
    names = [row["name"] for row in rows]
    exported = {row["name"]: row["file_private"] for row in rows}

    assert names.count("convert") == 1
    assert next(row for row in rows if row["name"] == "convert")["params"] == 1
    assert next(row for row in rows if row["name"] == "mapValues")["params"] == 2
    assert exported["mapValues"] is False
    assert exported["convert"] is False
    assert exported["unusedFunction"] is False
    assert exported["usedFunction"] is True


def test_typescript_roles_accessors_and_call_receivers():
    facts = extract_facts(
        "import { Get } from '@nestjs/common';\n"
        "class Base { render(): number { return 1; } }\n"
        "class Child extends Base {\n"
        "  get value(): number { return this._value; }\n"
        "  set value(next: number) { this._value = next; }\n"
        "  override render(): number { return this.send(1, 2); }\n"
        "  @Get('/value') endpoint() { return this.send(3); }\n"
        "}\n",
        "typescript",
    )
    rows = {(row["owner"], row["name"]): row for row in facts["functions"]}
    value_roles = [
        row["exempt_role"]
        for row in facts["functions"]
        if row["owner"] == "Child" and row["name"] == "value"
    ]

    assert value_roles == ["accessor", "accessor"]
    assert rows[("Child", "render")]["exempt_role"] == "override"
    assert rows[("Child", "endpoint")]["exempt_role"] == "handler"
    assert [
        (call["name"], call["receiver"], call["arity"]) for call in facts["call_sites"]
    ] == [("send", "self", 2), ("Get", None, 1), ("send", "self", 1)]


def test_typescript_parameter_property_constructor_and_readonly_getter():
    facts = extract_facts(
        "class Box {\n"
        " constructor(public readonly value: number) {}\n"
        " get id() { return this.value; }\n"
        "}\n",
        "typescript",
    )
    roles = {row["name"]: row["exempt_role"] for row in facts["functions"]}

    assert roles["constructor"] == "constructor"
    assert roles["id"] == "accessor"


def test_typescript_markers_and_name_checks():
    facts = extract_facts(
        "// auto-generated\nexport function util2(): number { return 1; }\n",
        "typescript",
    )

    assert facts["markers"] == ["generated"]
    assert facts["excluded"] is None
    assert facts["functions"][0]["name_issues"] == ["vague", "numbered"]


def test_tsx_arrow_and_jsx_callback_are_in_outer_function_span():
    facts = extract_facts(
        (
            "export const View = ({name}: Props) => "
            "<div onClick={() => go(name)}>{name}</div>;"
        ),
        "tsx",
        "view.tsx",
    )
    view = next(row for row in facts["functions"] if row["name"] == "View")

    assert view["params"] == 1
    assert view["file_private"] is False
    assert len(facts["functions"]) == 1
    assert facts["call_sites"] == [
        {
            "caller": view["id"],
            "name": "go",
            "receiver": None,
            "receiver_text": None,
            "arity": 1,
            "line": 1,
        }
    ]


def test_typescript_minified_detection_uses_dense_single_line_marker():
    source = "".join(f"const value{index}={index};" for index in range(100))
    facts = extract_facts(source, "typescript", "dense.ts")

    assert facts["excluded"] == "minified"
    below_threshold = extract_facts(
        "".join(f"const value{index}={index};" for index in range(99)),
        "typescript",
        "not-dense.ts",
    )
    assert below_threshold["excluded"] is None


def test_typescript_default_export_reexports_and_owner_scoped_exports():
    facts = extract_facts(
        "function App() { return 1; }\n"
        "export default App;\n"
        "function Wrapped() { return 2; }\n"
        "export default wrap(Wrapped);\n"
        "export function run() { return 1; }\n"
        "function publicAlias() { return 1; }\n"
        "export { publicAlias as renamed };\n"
        "function publicAlias() { return 1; }\n"
        "export { publicAlias as renamed };\n"
        "export var exportedVariable = () => 1;\n"
        "function localOnly() { return 2; }\n"
        "function caller() { return localOnly(); }\n"
        "function shadowed() { return 3; }\n"
        "function receivesShadowed(shadowed) { return shadowed; }\n"
        "export { localOnly as remote } from './other';\n"
        "class View { run() { return this.run(); } }\n",
        "typescript",
    )
    rows = {(row["owner"], row["name"]): row for row in facts["functions"]}

    assert rows[(None, "App")]["file_private"] is False
    assert rows[(None, "Wrapped")]["file_private"] is False
    assert rows[(None, "run")]["file_private"] is False
    assert rows[(None, "publicAlias")]["file_private"] is False
    assert rows[(None, "publicAlias")]["file_private"] is False
    assert rows[(None, "exportedVariable")]["file_private"] is False
    assert rows[("View", "run")]["file_private"] is True
    assert rows[(None, "localOnly")]["file_private"] is True
    assert rows[(None, "shadowed")]["file_private"] is False


def test_typescript_roles_require_known_imports_and_direct_methods():
    facts = extract_facts(
        (
            "import { Get as Fetch, Delete } from '@nestjs/common';\n"
            "import { Get } from './local';\n"
            "abstract class Base { abstract render(): number; }\n"
            "abstract class Controller extends Base {\n"
            " @Fetch(Delete) endpoint() { return 1; }\n"
            " @Get('/local') localEndpoint() { return 1; }\n"
            " override render() { return 2; }\n"
            " method() { function render() { return 3; } return render(); }\n"
            "}\n"
            "const Expression = class extends Controller { "
            "override render() { return 4; } };\n"
        ),
        "typescript",
    )
    render_roles = [
        row["exempt_role"] for row in facts["functions"] if row["name"] == "render"
    ]
    roles = {row["name"]: row["exempt_role"] for row in facts["functions"]}

    assert roles["endpoint"] == "handler"
    assert roles["localEndpoint"] is None
    assert render_roles == ["override", None, "override"]
    assert roles["method"] is None
    assert facts["functions"][-1]["exempt_role"] == "override"


def test_typescript_usage_conventions_this_parameter_and_module_calls():
    facts = extract_facts(
        "import * as utils from './utils';\n"
        "function snake_case(this: Thing, value: number) {\n"
        " const self = this; return self.send(utils.parsers.parse(value));\n"
        "}\n",
        "typescript",
    )
    function = facts["functions"][0]

    assert function["params"] == 1
    assert function["name_issues"] == ["convention"]
    assert [
        (call["name"], call["receiver"], call["arity"]) for call in facts["call_sites"]
    ] == [("send", "self", 1), ("parse", "mod", 1)]


def test_typescript_declaration_file_keeps_type_facts_for_path_classification():
    facts = extract_facts(
        "export interface Shape { x: number; }\n", "typescript", "shape.d.ts"
    )

    assert facts["path"] == "shape.d.ts"
    assert facts["tokens"] == 9
    assert facts["functions"] == []
