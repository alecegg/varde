from __future__ import annotations

import pytest
from varde_code.extract import extract_file
from varde_code.model import EntityKind

CASES = [
    (
        "bash",
        "sample.sh",
        "function alpha() { beta; }\nfunction beta() { :; }\n",
        {"alpha", "beta"},
    ),
    (
        "c",
        "sample.c",
        "void beta(void) {}\nvoid alpha(void) { beta(); }\n",
        {"alpha", "beta"},
    ),
    (
        "cpp",
        "sample.cpp",
        "void beta() {}\nvoid alpha() { beta(); }\n",
        {"alpha", "beta"},
    ),
    (
        "csharp",
        "Sample.cs",
        "class Sample { void Beta() {}\nvoid Alpha() { Beta(); } }\n",
        {"Alpha", "Beta"},
    ),
    (
        "dart",
        "sample.dart",
        "void beta() {}\nvoid alpha() { beta(); }\n",
        {"alpha", "beta"},
    ),
    (
        "elixir",
        "sample.ex",
        "defmodule Sample do\n  def beta, do: :ok\n  def alpha, do: beta()\nend\n",
        {"alpha", "beta"},
    ),
    (
        "go",
        "sample.go",
        "package sample\nfunc beta() {}\nfunc alpha() { beta() }\n",
        {"alpha", "beta"},
    ),
    ("haskell", "Sample.hs", "module Sample where\nbeta = 1\n", {"beta"}),
    (
        "java",
        "Sample.java",
        "class Sample { void beta() {}\nvoid alpha() { beta(); } }\n",
        {"alpha", "beta"},
    ),
    (
        "javascript",
        "sample.js",
        "function beta() {}\nfunction alpha() { beta(); }\n",
        {"alpha", "beta"},
    ),
    (
        "kotlin",
        "Sample.kt",
        "fun beta() {}\nfun alpha() { beta() }\n",
        {"alpha", "beta"},
    ),
    (
        "lua",
        "sample.lua",
        "function beta() end\nfunction alpha() beta() end\n",
        {"alpha", "beta"},
    ),
    (
        "php",
        "sample.php",
        "<?php\nfunction beta() {}\nfunction alpha() { beta(); }\n",
        {"alpha", "beta"},
    ),
    (
        "python",
        "sample.py",
        "def beta():\n    pass\ndef alpha():\n    beta()\n",
        {"alpha", "beta"},
    ),
    ("ruby", "sample.rb", "def beta; end\ndef alpha; beta; end\n", {"alpha", "beta"}),
    ("rust", "sample.rs", "fn beta() {}\nfn alpha() { beta(); }\n", {"alpha", "beta"}),
    (
        "scala",
        "Sample.scala",
        "object Sample { def beta() = 1\n def alpha() = beta() }\n",
        {"alpha", "beta"},
    ),
    (
        "swift",
        "Sample.swift",
        "func beta() {}\nfunc alpha() { beta() }\n",
        {"alpha", "beta"},
    ),
    (
        "typescript",
        "sample.ts",
        "function beta() {}\nfunction alpha() { beta(); }\n",
        {"alpha", "beta"},
    ),
]


@pytest.mark.parametrize("language,path,source,expected", CASES)
def test_language_extracts_authored_functions(language, path, source, expected):
    output = extract_file(path, source, language)
    names = {entity.name for entity in output.entities} | {
        symbol.name for symbol in output.symbols
    }
    assert expected <= names


@pytest.mark.parametrize(
    "language,path,source",
    [
        ("python", "broken.py", "def keep():\n    pass\n\ndef broken(:\n"),
        ("javascript", "broken.js", 'function keep() {}\nconst broken = "'),
        ("rust", "broken.rs", "fn keep() {}\nfn broken( {"),
    ],
)
def test_malformed_input_keeps_leading_function(language, path, source):
    output = extract_file(path, source, language)
    assert any(
        entity.kind == EntityKind.FUNCTION and entity.name == "keep"
        for entity in output.entities
    )


def test_python_function_call_is_attributed_to_its_caller():
    output = extract_file(
        "sample.py", "def alpha():\n    beta()\ndef beta():\n    pass\n", "python"
    )
    assert any(
        entity.kind == EntityKind.CALL
        and entity.name == "beta"
        and entity.enclosing_function == "alpha"
        for entity in output.entities
    )
