from varde_code.quality_pass.pathclass import (
    PathPredicates,
    classify_path,
    module_of,
    path_class_version,
)


def test_path_classes_use_index_flags_and_configured_path_rules():
    test_class = classify_path(
        "pkg/tests/test_item.py", PathPredicates(is_test_path=True), language="python"
    )
    tooling_class = classify_path(
        "pkg/scripts/build.py", PathPredicates(is_tooling_path=True), language="python"
    )
    vendor_class = classify_path(
        "pkg/vendor/lib.py", PathPredicates(), language="python"
    )
    glob_class = classify_path(
        "private/data.py",
        PathPredicates(exclusion_globs=("private/**",)),
        language="python",
    )

    assert test_class.test and not test_class.excluded
    assert test_class.scope_reasons == ("fast-index test path predicate",)
    assert tooling_class.tooling and not tooling_class.excluded
    assert tooling_class.scope_reasons == ("fast-index tooling path predicate",)
    assert (
        vendor_class.vendored
        and vendor_class.exclusion_reason == "vendored directory convention"
    )
    assert (
        glob_class.excluded
        and glob_class.exclusion_reason == "configured exclusion glob"
    )


def test_content_markers_do_not_change_path_classes_and_alone_do_not_gate_exclude():
    clean = classify_path("src/pkg/item.py", PathPredicates(), language="python")
    marker_gate = classify_path(
        "src/pkg/item.py",
        PathPredicates(generated_marker=True),
        language="python",
        gate_mode=True,
    )
    marker_report = classify_path(
        "src/pkg/item.py", PathPredicates(generated_marker=True), language="python"
    )
    convention_gate = classify_path(
        "src/pkg/generated/item.py",
        PathPredicates(generator_signature=True),
        language="python",
        gate_mode=True,
    )

    assert clean.generated == marker_gate.generated
    assert clean.excluded == marker_gate.excluded
    assert clean.module == marker_gate.module
    assert not marker_gate.generated
    assert (
        marker_report.excluded and marker_report.exclusion_reason == "generated marker"
    )
    assert convention_gate.excluded
    signature_gate = classify_path(
        "src/pkg/item.py",
        PathPredicates(generator_signature=True),
        language="python",
        gate_mode=True,
    )
    assert signature_gate.excluded
    assert signature_gate.exclusion_reason == "recognized generator signature"


def test_generated_directory_and_base_allowlist_are_explicitly_reported():
    directory = classify_path(
        "src/generated/model.py", PathPredicates(), language="python"
    )
    allowlisted_marker = classify_path(
        "src/model.py",
        PathPredicates(generated_marker=True, allowlisted_from_base=True),
        language="python",
        gate_mode=True,
    )

    assert directory.generated and directory.excluded
    assert directory.exclusion_reason == "generated directory convention"
    assert allowlisted_marker.generated and allowlisted_marker.excluded
    assert allowlisted_marker.exclusion_reason == "base-ref generated allowlist"


def test_path_specific_classes_and_module_assignment():
    predicates = PathPredicates()
    first = classify_path(
        "src/pkg/tests/item.py", PathPredicates(is_test_path=True), language="python"
    )
    second = classify_path("src/pkg/item.py", predicates, language="python")

    assert first.test and not second.test
    packages = {"src/pkg", "src/pkg/sub"}
    assert (
        module_of("src/pkg/sub/item.py", language="python", package_dirs=packages)
        == "src/pkg/sub"
    )
    assert (
        module_of("src/pkg/item.py", language="go", package_dirs=packages) == "src/pkg"
    )
    assert module_of("app/core/item.py", language="python") == "app/core"
    assert module_of("standalone.py", language="python") == "."


def test_same_content_marker_gets_path_dependent_classes():
    same_content = PathPredicates(generated_marker=True)
    vendor = classify_path("src/vendor/lib.py", same_content, language="python")
    project = classify_path("src/lib.py", same_content, language="python")

    assert vendor.generated == project.generated
    assert vendor.vendored and vendor.excluded
    assert not project.vendored and project.excluded


def test_vendored_default_is_case_insensitive_and_avoids_external():
    vendor = classify_path("lib/VENDOR/pkg.py", PathPredicates(), language="python")
    external = classify_path("src/external/api.py", PathPredicates(), language="python")
    node_modules = classify_path(
        "web/node_modules/pkg/index.js", PathPredicates(), language="javascript"
    )

    assert vendor.vendored and vendor.excluded
    assert not external.vendored
    assert node_modules.vendored


def test_exclusion_globs_normalize_separators_and_match_root_paths():
    recursive_root = classify_path(
        "item.py", PathPredicates(exclusion_globs=("**/item.py",)), language="python"
    )
    windows_path = classify_path(
        r"src\private\item.py",
        PathPredicates(exclusion_globs=("src/private/*.py",)),
        language="python",
    )

    assert recursive_root.exclusion_reason == "configured exclusion glob"
    assert windows_path.exclusion_reason == "configured exclusion glob"


def test_path_class_version_tracks_predicate_configuration():
    assert path_class_version(PathPredicates()) != path_class_version(
        PathPredicates(exclusion_globs=("generated/**",))
    )
    assert path_class_version(PathPredicates()) != path_class_version(
        PathPredicates(vendored_dirs=("third_party",))
    )
    assert path_class_version(PathPredicates()) != path_class_version(
        PathPredicates(generated_dirs=("autogen",))
    )
    assert path_class_version(package_dirs=("src/pkg",)) != path_class_version(
        package_dirs=("src/pkg", "src/pkg/sub")
    )
    assert path_class_version() == path_class_version()


def test_externals_directory_is_vendored_by_default():
    path_class = classify_path(
        "pkg/externals/array_api_compat/fft.py", PathPredicates(), language="python"
    )
    assert path_class.vendored
    assert path_class.excluded
