"""Behavior tests for ground-truth target id parsing and matching."""

import pytest
from audit.targets import TargetKey, parse_target_id, target_keys_match


@pytest.mark.parametrize(
    ("target_id", "expected"),
    [
        (
            "django/conf/global_settings.py::gettext_noop@9",
            TargetKey("django/conf/global_settings.py", "gettext_noop", 9),
        ),
        (
            "django/apps/config.py::AppConfig.create@100",
            TargetKey("django/apps/config.py", "create", 100),
        ),
        (
            "src/cli/format-results-cache.js::#getFileDescriptor@110",
            TargetKey("src/cli/format-results-cache.js", "#getFileDescriptor", 110),
        ),
        (
            "src/index.d.ts::formatWithCursor@611",
            TargetKey("src/index.d.ts", "formatWithCursor", 611),
        ),
    ],
)
def test_python_ts_ids_keep_file_declared_name_and_line(target_id, expected):
    language = "typescript" if target_id.startswith("src/") else "python"

    assert parse_target_id(language, target_id) == expected


@pytest.mark.parametrize(
    ("language", "target_id", "expected"),
    [
        (
            "go",
            "build/openapi3gen/enumscan.go:145:registerEnumAnnotation",
            TargetKey("build/openapi3gen/enumscan.go", "registerEnumAnnotation", 145),
        ),
        (
            "rust",
            "rayon-core/src/lib.rs:239:new",
            TargetKey("rayon-core/src/lib.rs", "new", 239),
        ),
        (
            "go",
            "cmd/web_https.go:46:lookupAll",
            TargetKey("cmd/web_https.go", "lookupAll", 46),
        ),
        (
            "go",
            "modelmigration/migrations.go:53:newMigration",
            TargetKey("modelmigration/migrations.go", "newMigration", 53),
        ),
        (
            "rust",
            "rayon-core/src/thread_pool/test.rs:68:count_handler",
            TargetKey("rayon-core/src/thread_pool/test.rs", "count_handler", 68),
        ),
        (
            "cpp",
            "absl/base/internal/low_level_alloc.cc:165:LLA_SkiplistSearch",
            TargetKey(
                "absl/base/internal/low_level_alloc.cc", "LLA_SkiplistSearch", 165
            ),
        ),
        (
            "cpp",
            "absl/functional/function_ref.h:164:operator()",
            TargetKey("absl/functional/function_ref.h", "operator()", 164),
        ),
    ],
)
def test_go_rust_cpp_ids_keep_operator_names_literal(language, target_id, expected):
    assert parse_target_id(language, target_id) == expected


@pytest.mark.parametrize(
    ("language", "target_id", "expected"),
    [
        (
            "java",
            (
                "jablib/src/main/java/org/jabref/logic/ai/preferences/AiPreferences.java::"
                "org.jabref.logic.ai.preferences.AiPreferences.getHuggingFaceChatModel()"
            ),
            TargetKey(
                "jablib/src/main/java/org/jabref/logic/ai/preferences/AiPreferences.java",
                "getHuggingFaceChatModel",
                None,
            ),
        ),
        (
            "java",
            (
                "jablib/src/main/java/org/jabref/logic/ai/tokenization/logic/"
                "MaximumTokenEstimator.java::org.jabref.logic.ai.tokenization.logic."
                "MaximumTokenEstimator.calculate(int,int)"
            ),
            TargetKey(
                "jablib/src/main/java/org/jabref/logic/ai/tokenization/logic/"
                "MaximumTokenEstimator.java",
                "calculate",
                None,
            ),
        ),
        (
            "java",
            (
                "jablib/src/main/java/org/jabref/model/entry/LinkedFile.java::"
                "org.jabref.model.entry.LinkedFile.getSourceUrl()"
            ),
            TargetKey(
                "jablib/src/main/java/org/jabref/model/entry/LinkedFile.java",
                "getSourceUrl",
                None,
            ),
        ),
        (
            "csharp",
            (
                "src/Http/Authentication.Abstractions/src/AuthenticateResult.cs::"
                "Microsoft.AspNetCore.Authentication.AuthenticateResult.Fail("
                "System.Exception, Microsoft.AspNetCore.Authentication."
                "AuthenticationProperties?)"
            ),
            TargetKey(
                "src/Http/Authentication.Abstractions/src/AuthenticateResult.cs",
                "Fail",
                None,
            ),
        ),
        (
            "csharp",
            (
                "src/Compilers/Core/CodeAnalysisTest/Collections/ImmutableSetTest.cs::"
                "Microsoft.CodeAnalysis.UnitTests.Collections.ImmutableSetTest.Empty<int>()"
            ),
            TargetKey(
                "src/Compilers/Core/CodeAnalysisTest/Collections/ImmutableSetTest.cs",
                "Empty",
                None,
            ),
        ),
        (
            "csharp",
            (
                "src/Http/Http.Abstractions/src/Routing/EndpointMetadataCollection.cs::"
                "Microsoft.AspNetCore.Http.EndpointMetadataCollection.GetMetadata<"
                "Microsoft.AspNetCore.Routing.IHttpMethodMetadata>()"
            ),
            TargetKey(
                "src/Http/Http.Abstractions/src/Routing/EndpointMetadataCollection.cs",
                "GetMetadata",
                None,
            ),
        ),
        (
            "csharp",
            (
                "src/Umbraco.Infrastructure/Migrations/Install/DatabaseDataCreator.cs::"
                "Umbraco.Cms.Infrastructure.Migrations.Install.DatabaseDataCreator."
                "ConditionalInsert<Umbraco.Cms.Infrastructure.Persistence.Dtos.NodeDto>("
                "string, string, Umbraco.Cms.Infrastructure.Persistence.Dtos.NodeDto, "
                "string, string, bool)"
            ),
            TargetKey(
                "src/Umbraco.Infrastructure/Migrations/Install/DatabaseDataCreator.cs",
                "ConditionalInsert",
                None,
            ),
        ),
    ],
)
def test_member_signature_ids_drop_parameters_and_generic_arguments(
    language, target_id, expected
):
    assert parse_target_id(language, target_id) == expected


def test_java_constructor_marker_maps_to_the_enclosing_type_name():
    target_id = (
        "jablib/src/main/java/org/jabref/logic/exporter/AtomicFileOutputStream.java::"
        "org.jabref.logic.exporter.AtomicFileOutputStream.<init>(java.nio.file.Path,"
        "boolean,org.jabref.logic.util.io.FileSnapshot)"
    )

    key = parse_target_id("java", target_id)

    assert key.name == "AtomicFileOutputStream"
    assert key.line is None


def test_annotation_marks_inside_parameters_do_not_confuse_the_line_grammar():
    target_id = (
        "guava/src/com/google/common/base/Platform.java::com.google.common.base."
        "Platform.lenientFormat(java.lang.String,java.lang.Object @Nullable [])"
    )

    key = parse_target_id("java", target_id)

    assert key == TargetKey(
        "guava/src/com/google/common/base/Platform.java", "lenientFormat", None
    )


def test_java_method_name_is_preserved_with_dotted_generic_parameter_types():
    target_id = (
        "jablib/src/main/java/org/jabref/openoffice/style/JStyle.java::"
        "org.jabref.logic.openoffice.style.JStyle.handlePropertiesLine(java.lang.String,"
        "java.util.Map<java.lang.String,java.lang.Object>)"
    )

    assert parse_target_id("java", target_id).name == "handlePropertiesLine"


def test_match_requires_the_same_file_and_declared_name():
    measured = TargetKey("lib/a.cpp", "run", 10)
    truth = TargetKey("lib/b.cpp", "run", 10)

    assert target_keys_match(measured, truth) is False


def test_match_requires_equal_lines_when_the_target_carries_one():
    truth = TargetKey("lib/a.cpp", "run", 10)

    assert target_keys_match(TargetKey("lib/a.cpp", "run", 10), truth) is True
    assert target_keys_match(TargetKey("lib/a.cpp", "run", 12), truth) is False


def test_match_is_lenient_for_line_less_overloads():
    truth = TargetKey("src/Ai.java", "calculate", None)

    assert target_keys_match(TargetKey("src/Ai.java", "calculate", 42), truth) is True


def test_real_java_overloads_collapse_to_one_key_and_both_match():
    overloads = [
        (
            "src/main/java/org/apache/commons/io/Charsets.java::"
            "org.apache.commons.io.Charsets.toCharset(java.lang.String)"
        ),
        (
            "src/main/java/org/apache/commons/io/Charsets.java::"
            "org.apache.commons.io.Charsets.toCharset(java.nio.charset.Charset)"
        ),
    ]

    keys = [parse_target_id("java", target_id) for target_id in overloads]

    assert keys[0] == keys[1]
    assert all(
        target_keys_match(TargetKey(keys[0].file, "toCharset", 55), key) for key in keys
    )


@pytest.mark.parametrize(
    ("language", "target_id"),
    [
        ("python", "django/apps/config.py::AppConfig.create"),
        ("python", "django/apps/config.py::AppConfig.create@zero"),
        ("go", "build/openapi3gen/enumscan.go::registerEnumAnnotation"),
        ("java", "AiPreferences.java:AiPreferences.getSourceUrl()"),
        ("pascal", "unit.pas:4:Run"),
    ],
)
def test_malformed_or_unknown_target_ids_raise(language, target_id):
    with pytest.raises(ValueError):
        parse_target_id(language, target_id)


def test_anonymous_truth_matches_any_name_at_same_file_and_line():
    truth = parse_target_id("typescript", "src/a.ts::<anonymous>@7")

    assert target_keys_match(TargetKey("src/a.ts", "handler", 7), truth) is True
    assert target_keys_match(TargetKey("src/a.ts", "handler", 8), truth) is False
    assert target_keys_match(TargetKey("src/b.ts", "handler", 7), truth) is False


def test_cpp_anonymous_truth_matches_any_name_at_same_file_and_line():
    truth = parse_target_id("cpp", "src/a.cpp:7:<anonymous>")

    assert target_keys_match(TargetKey("src/a.cpp", "handler", 7), truth) is True
    assert target_keys_match(TargetKey("src/a.cpp", "other", 7), truth) is True


def test_non_anonymous_truth_still_requires_equal_names():
    truth = TargetKey("src/a.ts", "handler", 7)

    assert target_keys_match(TargetKey("src/a.ts", "other", 7), truth) is False


def test_line_less_anonymous_truth_is_not_a_wildcard():
    truth = TargetKey("A.java", "<anonymous>", None)

    assert target_keys_match(TargetKey("A.java", "foo", 3), truth) is False
