def pytest_addoption(parser: Parser) -> None:
    group = parser.getgroup("debugconfig")
    group.addoption(
        "--assert",
        action="store",
        dest="assertmode",
        choices=("rewrite", "plain"),
        default="rewrite",
        metavar="MODE",
        help=(
            "Control assertion debugging tools.\n"
            "'plain' performs no assertion debugging.\n"
            "'rewrite' (the default) rewrites assert statements in test modules"
            " on import to provide assert expression information."
        ),
    )
    parser.addini(
        "enable_assertion_pass_hook",
        type="bool",
        default=False,
        help="Enables the pytest_assertion_pass hook. "
        "Make sure to delete any previously generated pyc cache files.",
    )

    # ``int | str`` (not plain ``int``) for backward compatibility: INI files
    # and ``-o`` overrides provide the value as a string.
    parser.addini(
        "truncation_limit_lines",
        type=int | str,
        default=None,
        help="Set threshold of LINES after which truncation will take effect",
    )
    parser.addini(
        "truncation_limit_chars",
        type=int | str,
        default=None,
        help=("Set threshold of CHARS after which truncation will take effect"),
    )
    parser.addini(
        "assertion_text_diff_style",
        type=_AssertionTextDiffStyle,
        default="ndiff",
        help="Choose how pytest renders diffs for string equality assertions",
    )

    Config._add_verbosity_ini(
        parser,
        Config.VERBOSITY_ASSERTIONS,
        help=(
            "Specify a verbosity level for assertions, overriding the main level. "
            "Higher levels will provide more detailed explanation when an assertion fails."
        ),
    )
