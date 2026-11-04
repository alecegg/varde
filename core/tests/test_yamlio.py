from varde_core.yamlio import dump_yaml, load_yaml


def test_yaml_round_trip_preserves_hand_written_values() -> None:
    fixtures = [
        ("key: value\n", {"key": "value"}),
        ("type: decision\ntitle: Test\n", {"type": "decision", "title": "Test"}),
        ("{}\n", {}),
    ]
    for fixture, value in fixtures:
        assert load_yaml(fixture) == value
        assert dump_yaml(value) == f"---\n{fixture}"


def test_yaml_scalar_rendering_and_yaml_12_loading() -> None:
    values = [
        (
            "description",
            "word " * 8,
            "description: 'word word word word word word word word '",
        ),
        ("description", "a\nb\n", "description: |\n  a\n  b"),
        ("yes", "yes", "yes: yes"),
        ("date", "2020-01-01", "date: 2020-01-01"),
        ("equals", "=", "equals: ="),
        ("exponent", "1e3", "exponent: '1e3'"),
        ("colon", ":value", "colon: :value"),
        ("question", "?value", "question: ?value"),
        ("hex", "0x1f", "hex: '0x1f'"),
        ("octal", "0o7", "octal: '0o7'"),
        ("tab", "a\tb", 'tab: "a\\tb"'),
    ]
    for key, value, expected in values:
        rendered = dump_yaml({key: value})
        assert rendered.splitlines()[1:] == expected.splitlines()

    loaded = load_yaml("yes: yes\non: on\ndate: 2020-01-01\nexponent: 1e3\n")
    assert loaded == {
        "yes": "yes",
        "on": "on",
        "date": "2020-01-01",
        "exponent": 1000.0,
    }


def test_yaml_syntax_error_has_compact_message() -> None:
    import pytest
    from varde_core.yamlio import YamlSyntaxError

    with pytest.raises(YamlSyntaxError, match="did not find expected") as error:
        load_yaml("not: [valid")
    assert str(error.value) == (
        "did not find expected ',' or ']' at line 2 column 1, "
        "while parsing a flow sequence at line 1 column 6"
    )


def test_load_yaml_caches_c_loader_when_available() -> None:
    import yaml
    from varde_core import yamlio

    yamlio.load_yaml("value: true")
    loader = yamlio._core_loader(yaml.__with_libyaml__)
    expected_base = yaml.CSafeLoader if yaml.__with_libyaml__ else yaml.SafeLoader
    assert issubclass(loader, expected_base)
    assert loader is yamlio._core_loader(yaml.__with_libyaml__)


def test_load_yaml_caches_pure_python_fallback(monkeypatch) -> None:
    import yaml
    from varde_core import yamlio

    monkeypatch.setattr(yaml, "__with_libyaml__", False)
    yamlio._core_loader.cache_clear()
    loader = yamlio._core_loader(yaml.__with_libyaml__)
    assert issubclass(loader, yaml.SafeLoader)
    assert loader is yamlio._core_loader(yaml.__with_libyaml__)


def test_yaml_syntax_errors_match_with_and_without_libyaml(monkeypatch) -> None:
    import pytest
    import yaml
    from varde_core import yamlio
    from varde_core.yamlio import YamlSyntaxError

    malformed = (
        "a: b: c",
        "a: @x",
        "a: 'x",
        "a: [",
        "a: &x\nb: *y",
        "a:\n\t- x",
        "a: ]",
        'a: "unterminated',
        "a: {",
    )
    has_libyaml = yaml.__with_libyaml__

    for text in malformed:
        messages = []
        for use_c_loader in (has_libyaml, False):
            monkeypatch.setattr(yaml, "__with_libyaml__", use_c_loader)
            yamlio._core_loader.cache_clear()
            with pytest.raises(YamlSyntaxError) as error:
                yamlio.load_yaml(text)
            messages.append(str(error.value))
        assert messages[0] == messages[1], text


def test_yaml_float_overflow_remains_text_and_finite_values_stay_float() -> None:
    assert load_yaml("base: 6417e875\n") == {"base": "6417e875"}
    assert load_yaml("base: 1e5\n") == {"base": 100000.0}
    assert load_yaml("base: 62995e08\n") == {"base": 6299500000000.0}


def test_explicit_inf_literal_still_loads_as_float() -> None:
    assert load_yaml("a: .inf\n") == {"a": float("inf")}
