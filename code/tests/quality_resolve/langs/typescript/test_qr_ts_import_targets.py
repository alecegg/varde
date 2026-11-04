from varde_code.quality_resolve import edges_for_file, prepare
from varde_code.quality_resolve.langs.typescript import import_bindings, import_targets


def test_named_import_tracks_names_and_aliases():
    paths = ("src/main.ts", "src/lib.ts")
    assert import_bindings(
        {
            "module": "./lib",
            "text": "import { work as w, other } from './lib';",
        },
        "src/main.ts",
        paths,
        {},
    ) == [
        {
            "path": "src/lib.ts",
            "names": ["other"],
            "aliases": {"w": "work"},
            "binding": None,
        }
    ]


def test_default_import_tracks_default_alias():
    paths = ("src/main.ts", "src/lib.ts")
    assert import_bindings(
        {"module": "./lib", "text": "import lib from './lib';"},
        "src/main.ts",
        paths,
        {},
    ) == [{"path": "src/lib.ts", "names": [], "aliases": {}, "binding": None}]


def test_namespace_import_binds_receiver_alias():
    paths = ("src/main.ts", "src/lib.ts")
    assert import_bindings(
        {"module": "./lib", "text": "import * as ns from './lib';"},
        "src/main.ts",
        paths,
        {},
    ) == [{"path": "src/lib.ts", "names": [], "aliases": {}, "binding": "ns"}]


def test_typescript_namespace_binding_resolves_receiver_call():
    facts = {
        "src/main.ts": {
            "imports": [
                {
                    "module": "./lib",
                    "line": 1,
                    "text": "import * as ns from './lib';",
                }
            ],
            "call_sites": [{"name": "work", "receiver_text": "ns"}],
        },
        "src/lib.ts": {"functions": [{"id": "lib-work", "name": "work"}]},
    }
    edge = edges_for_file(prepare(facts, facts), "src/main.ts")[0]
    assert (edge["kind"], edge["pass"], edge["callee"]) == (
        "resolved",
        "receiver",
        "lib-work",
    )


def test_default_and_named_imports_share_one_binding():
    paths = ("src/main.ts", "src/lib.ts")
    assert import_bindings(
        {"module": "./lib", "text": "import lib, { work as w } from './lib';"},
        "src/main.ts",
        paths,
        {},
    ) == [
        {
            "path": "src/lib.ts",
            "names": [],
            "aliases": {"w": "work"},
            "binding": None,
        }
    ]


def test_unknown_import_form_binds_nothing():
    paths = ("src/main.ts", "src/lib.ts")
    assert import_bindings(
        {"module": "./lib", "text": "import lib = require('./lib');"},
        "src/main.ts",
        paths,
        {},
    ) == [{"path": "src/lib.ts", "names": [], "aliases": {}, "binding": None}]


def test_relative_import_resolves_extensionless_module():
    paths = ("src/main.ts", "src/lib/helper.ts")
    assert import_targets({"module": "./lib/helper"}, "src/main.ts", paths, {}) == [
        "src/lib/helper.ts"
    ]


def test_relative_import_resolves_index_module():
    paths = ("src/main.ts", "src/lib/index.tsx")
    assert import_targets({"module": "./lib"}, "src/main.ts", paths, {}) == [
        "src/lib/index.tsx"
    ]


def test_parent_relative_import_resolves_normalized_path():
    paths = ("src/main.ts", "lib/helper.ts")
    assert import_targets({"module": "../lib/helper"}, "src/main.ts", paths, {}) == [
        "lib/helper.ts"
    ]


def test_javascript_extension_resolves_typescript_source():
    paths = ("src/main.ts", "src/lib/helper.ts")
    assert import_targets({"module": "./lib/helper.js"}, "src/main.ts", paths, {}) == [
        "src/lib/helper.ts"
    ]


def test_non_relative_import_is_not_repo_wide_resolved():
    paths = ("src/main.ts", "src/library.ts")
    assert import_targets({"module": "library"}, "src/main.ts", paths, {}) == []


def test_ambiguous_relative_import_remains_unresolved():
    paths = ("src/main.ts", "src/helper.ts", "src/helper.js")
    assert import_targets({"module": "./helper"}, "src/main.ts", paths, {}) == []


def test_dotted_filename_without_extension_resolves_source_extension():
    paths = ("src/main.ts", "src/user.service.ts")
    assert import_targets({"module": "./user.service"}, "src/main.ts", paths, {}) == [
        "src/user.service.ts"
    ]


def test_inline_type_specifier_does_not_drop_value_import():
    paths = ("src/main.ts", "src/lib.ts")
    assert import_bindings(
        {"module": "./lib", "text": "import {type X, work} from './lib';"},
        "src/main.ts",
        paths,
        {},
    ) == [{"path": "src/lib.ts", "names": ["work"], "aliases": {}, "binding": None}]
