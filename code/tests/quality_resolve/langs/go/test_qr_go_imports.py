import importlib

from varde_code.quality_resolve import edges_for_file, prepare
from varde_code.quality_resolve.langs.go import import_bindings


def test_import_targets_maps_module_path_to_package_directory():
    from varde_code.quality_resolve.langs.go import import_targets

    files = (
        "cmd/app/main.go",
        "internal/format/format.go",
        "internal/format/format_test.go",
        "internal/other/format.go",
    )
    facts = {path: {} for path in files}

    assert import_targets(
        {"line": 3, "module": "example.com/project/internal/format"},
        "cmd/app/main.go",
        files,
        facts,
    ) == ["internal/format/format.go"]


def test_import_targets_rejects_partial_suffix_overlap():
    from varde_code.quality_resolve.langs.go import import_targets

    for directory, module in (
        ("tp/testify/assert/assert.go", "github.com/stretchr/testify/assert"),
        ("b/x/util/util.go", "github.com/third/a/x/util"),
    ):
        assert import_targets({"module": module}, "main.go", (directory,), {}) == []


def test_import_targets_rejects_stdlib_shaped_suffix():
    from varde_code.quality_resolve.langs.go import import_targets

    assert (
        import_targets(
            {"module": "net/http"}, "main.go", ("internal/net/http/http.go",), {}
        )
        == []
    )


def test_import_targets_uses_host_path_suffix_for_vendored_dirs():
    from varde_code.quality_resolve.langs.go import import_targets

    assert import_targets(
        {"module": "github.com/acme/net/http"},
        "main.go",
        ("vendor/github.com/acme/net/http/http.go",),
        {},
    ) == ["vendor/github.com/acme/net/http/http.go"]


def test_import_binding_uses_package_fact_for_default_name():
    files = ("cmd/main.go", "a/util/u.go")
    facts = {"a/util/u.go": {"package": "helpers"}}
    assert import_bindings(
        {"module": "example.com/a/util", "text": '"example.com/a/util"'},
        "cmd/main.go",
        files,
        facts,
    ) == [{"path": "a/util/u.go", "names": [], "binding": "helpers"}]


def test_prepare_passes_import_spec_to_go_hook(monkeypatch):
    module = importlib.import_module("varde_code.quality_resolve.langs.go")
    original = module.import_targets
    seen = []

    def recording_hook(spec, importer_path, file_set, context):
        seen.append((spec, importer_path))
        return original(spec, importer_path, file_set, context)

    monkeypatch.setattr(module, "import_targets", recording_hook)
    facts = {
        "cmd/app/main.go": {
            "imports": [
                {
                    "line": 3,
                    "module": "example.com/project/internal/format",
                    "text": '"example.com/project/internal/format"',
                }
            ]
        },
        "internal/format/format.go": {},
    }

    prepare(facts, facts)

    assert seen == [
        (
            {
                "line": 3,
                "module": "example.com/project/internal/format",
                "text": '"example.com/project/internal/format"',
            },
            "cmd/app/main.go",
        ),
        (
            {
                "line": 3,
                "module": "example.com/project/internal/format",
                "text": '"example.com/project/internal/format"',
            },
            "cmd/app/main.go",
        ),
    ]


def test_package_receiver_resolves_when_import_binding_is_present():
    facts = {
        "cmd/app/main.go": {
            "imports": [
                {
                    "line": 3,
                    "module": "example.com/project/internal/format",
                    "text": 'fmt "example.com/project/internal/format"',
                }
            ],
            "call_sites": [
                {
                    "caller": "Run",
                    "name": "Format",
                    "receiver_text": "fmt",
                    "arity": 0,
                }
            ],
        },
        "internal/format/format.go": {
            "functions": [{"id": "format", "name": "Format", "params": 0}]
        },
    }

    assert edges_for_file(prepare(facts, facts), "cmd/app/main.go")[0] == {
        "caller": "Run",
        "site_line": None,
        "callee": "format",
        "kind": "resolved",
        "pass": "receiver",
    }


def test_import_bindings_uses_package_name_alias_or_dot_import_names():
    files = ("cmd/app/main.go", "internal/format/format.go")
    context = {path: {} for path in files}

    assert import_bindings(
        {
            "module": "example.com/project/internal/format",
            "text": '"example.com/project/internal/format"',
        },
        "cmd/app/main.go",
        files,
        context,
    ) == [{"path": "internal/format/format.go", "names": [], "binding": "format"}]
    assert import_bindings(
        {
            "module": "example.com/project/internal/format",
            "text": 'fmtx "example.com/project/internal/format"',
        },
        "cmd/app/main.go",
        files,
        context,
    ) == [{"path": "internal/format/format.go", "names": [], "binding": "fmtx"}]
    assert import_bindings(
        {
            "module": "example.com/project/internal/format",
            "text": '. "example.com/project/internal/format"',
        },
        "cmd/app/main.go",
        files,
        context,
    ) == [{"path": "internal/format/format.go", "names": "*", "binding": None}]


def test_dot_import_exposes_bare_calls_from_the_package():
    facts = {
        "cmd/app/main.go": {
            "imports": [
                {
                    "line": 1,
                    "module": "example.com/project/internal/format",
                    "text": '. "example.com/project/internal/format"',
                }
            ],
            "call_sites": [{"caller": "Run", "name": "Format", "arity": 0}],
        },
        "internal/format/format.go": {
            "functions": [{"id": "format", "name": "Format", "params": 0}]
        },
    }

    edge = edges_for_file(prepare(facts, facts), "cmd/app/main.go")[0]
    assert (edge["kind"], edge["pass"], edge["callee"]) == (
        "resolved",
        "imported",
        "format",
    )


def test_aliased_package_receiver_uses_exact_import_text():
    facts = {
        "cmd/app/main.go": {
            "imports": [
                {
                    "line": 1,
                    "module": "example.com/project/internal/format",
                    "text": 'fmtx "example.com/project/internal/format"',
                }
            ],
            "call_sites": [
                {"caller": "Run", "name": "Format", "receiver_text": "fmtx"}
            ],
        },
        "internal/format/format.go": {
            "functions": [{"id": "format", "name": "Format"}]
        },
    }

    edge = edges_for_file(prepare(facts, facts), "cmd/app/main.go")[0]
    assert (edge["kind"], edge["pass"], edge["callee"]) == (
        "resolved",
        "receiver",
        "format",
    )


def test_unknown_or_blank_import_text_does_not_expose_package_calls():
    files = ("cmd/app/main.go", "internal/format/format.go")
    context = {path: {} for path in files}
    for text in ('_ "example.com/project/internal/format"', "unknown syntax"):
        assert import_bindings(
            {"module": "example.com/project/internal/format", "text": text},
            "cmd/app/main.go",
            files,
            context,
        ) == [
            {
                "path": "internal/format/format.go",
                "names": [],
                "binding": None,
            }
        ]
