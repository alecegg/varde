from varde_code.rules.dependency_facts.c_cpp import scan_includes
from varde_code.rules.dependency_facts.elixir_haskell import (
    collect_manifest_modules,
    elixir_modules,
    haskell_module,
    is_generated_module,
    scan_haskell_imports,
)
from varde_code.rules.dependency_facts.lua_bash import (
    is_literal_relative_path,
    is_lua_module,
)
from varde_code.rules.dependency_facts.ruby_php import php_requires, ruby_requires


def flags(text: str) -> list[tuple[str, bool, bool]]:
    return [(item.spec, item.quoted, item.conditional) for item in scan_includes(text)]


def test_whole_file_guard_is_not_conditional():
    text = '#ifndef X_H\n#define X_H\n#include "a.h"\n#include <b.h>\n#endif\n'
    assert flags(text) == [("a.h", True, False), ("b.h", False, False)]


def test_nested_conditionals_and_non_guards_are_conditional():
    guarded = '#ifndef X_H\n#define X_H\n#ifdef Y\n#include "a.h"\n#endif\n#endif\n'
    assert flags(guarded) == [("a.h", True, True)]
    trailing = '#ifndef X_H\n#define X_H\n#endif\n#include "a.h"\n'
    assert flags(trailing) == [("a.h", True, False)]
    not_guard = '#ifndef X_H\n#include "a.h"\n#endif\n'
    assert flags(not_guard) == [("a.h", True, True)]


def test_comments_and_continuations_are_handled():
    text = (
        '/* #include "no.h" */ // #include "no2.h"\n#  include "yes.h" // c\n'
        '#define X \\\n #include "no3.h"\n'
    )
    assert flags(text) == [("yes.h", True, False)]


def test_lua_module_names_and_bash_literal_paths():
    assert all(
        is_lua_module(value) for value in ["a", "a/b", "kong/tools/utils", "a-b_c"]
    )
    assert not any(
        is_lua_module(value)
        for value in ["", "/a", "a/", "a//b", "a b", "a?b", "$a", "a/b.c"]
    )
    assert all(
        is_literal_relative_path(value)
        for value in ["./x.sh", "../lib/x.sh", "./a/b.bash", "./a_b-c+d.sh"]
    )
    assert not any(
        is_literal_relative_path(value)
        for value in [
            "x.sh",
            "/etc/os-release",
            "$DIR/x.sh",
            "${DIR}/x.sh",
            '$(dirname "$0")/x.sh',
            "./x*.sh",
            '"./x y.sh"',
            "./x/",
            "./x//y.sh",
            "~/.x.sh",
            "./x.sh;rm",
        ]
    )


def test_elixir_module_names_and_haskell_module_headers():
    assert elixir_modules(
        "defmodule MyApp do\n  defmodule Foo do\n  end\nend\ndefmodule Other do\nend\n"
    ) == ["MyApp", "MyApp.Foo", "Other"]
    assert (
        elixir_modules(
            "defmodule unquote(name) do\nend\ndefmodule #{inspect(owner)} do\nend\n"
        )
        == []
    )
    assert elixir_modules("defprotocol Livebook.FileSystem do\nend\n") == [
        "Livebook.FileSystem"
    ]
    assert haskell_module("module Data.List (sort) where\n") == "Data.List"
    assert haskell_module("main = pure ()\n") is None


def test_haskell_import_guards_pragmas_and_generated_names():
    scanned = scan_haskell_imports("#ifdef X\nimport Guarded\n#endif\nimport Plain\n")
    assert scanned == [("Guarded", True), ("Plain", False)]
    assert scan_haskell_imports("import {-# SOURCE #-} App.Real\n") == [
        ("App/Real", False)
    ]
    assert is_generated_module("Paths_pandoc")
    assert is_generated_module("Foo/Paths_bar")
    assert not any(is_generated_module(value) for value in ["Paths", "App/Core/Gone"])


def test_haskell_manifest_module_fields():
    cabal = (
        "library\n  hs-source-dirs: src\n  exposed-modules: Text.Pandoc,\n"
        "                   Text.Pandoc.App,\n"
        "                   Text.Pandoc.XML.Light.Types\n"
        "  build-depends: base >= 4.14\n  other-modules: Paths_pandoc\n"
    )
    modules: set[str] = set()
    collect_manifest_modules(cabal, modules)
    assert {
        "Text.Pandoc",
        "Text.Pandoc.App",
        "Text.Pandoc.XML.Light.Types",
        "Paths_pandoc",
    } <= modules
    assert "base" not in modules


def test_ruby_require_certification_and_guarding():
    actual = [
        (item.spec, item.certifiable, item.missing_eligible)
        for item in ruby_requires(
            "require_relative 'b'\nrequire 'json'\nrequire_relative '../lib/util'\n"
        )
    ]
    assert actual == [
        ("b", True, True),
        ("json", False, False),
        ("../lib/util", True, True),
    ]
    guarded = ruby_requires("begin\n  require_relative 'gone'\nrescue LoadError\nend\n")
    assert [
        (item.spec, item.certifiable, item.missing_eligible) for item in guarded
    ] == [("gone", False, False)]
    dynamic = ruby_requires('require_relative "#{dir}/gone"\n')
    assert [
        (item.spec, item.certifiable, item.missing_eligible) for item in dynamic
    ] == [("/gone", False, False)]


def test_php_require_certification_and_suppression():
    actual = [
        (item.spec, item.certifiable, item.missing_eligible)
        for item in php_requires(
            (  # noqa: UP034 - grouping keeps adjacent fixture literals clear
                "<?php\nrequire_once 'b.php';\nrequire './gone.php';\n"
                "require __DIR__ . '/x.php';\n"
            )
        )
    ]
    assert actual == [("b.php", True, False), ("./gone.php", True, True)]
    actual = [
        (item.spec, item.certifiable, item.missing_eligible)
        for item in php_requires(
            (  # noqa: UP034 - grouping keeps adjacent fixture literals clear
                "<?php\n@include './x.php';\n$f = './y.php';\ninclude $f;\n"
                'include "$dir/z.php";\n'
            )
        )
    ]
    assert actual == [("./x.php", False, False), ("/z.php", False, False)]
