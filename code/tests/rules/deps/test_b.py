from varde_code.rules.dependency_facts import csharp_swift, jvm
from varde_code.rules.dependency_facts.types import FactInput, FileRow, ImportRow


def test_java_declarations_and_import_forms():
    parsed = jvm.parse_file(
        """package com.example.alpha;
import com.example.beta.Beta;
import static com.example.beta.Beta.VALUE;
import com.example.beta.*;
public final class Alpha extends Base {}
interface Helper {}
""",
        "java",
    )
    assert parsed.package == "com.example.alpha"
    assert parsed.declared == ["Alpha", "Helper"]
    assert parsed.imports == [
        ("com/example/beta/Beta", True),
        ("com/example/beta/Beta/VALUE", False),
        ("com/example/beta", False),
    ]


def test_kotlin_declarations_and_import_forms():
    parsed = jvm.parse_file(
        """package com.example.alpha
import com.example.beta.Beta
import com.example.beta.Beta as B
import com.example.beta.*
data class Alpha(val x: Int)
fun String.extension() = this
fun topLevel() = 1
val answer = 42
object Registry
""",
        "kotlin",
    )
    assert parsed.declared == ["Alpha", "extension", "topLevel", "answer", "Registry"]
    assert [plain for _, plain in parsed.imports] == [True, True, False]


def test_scala_declarations_and_import_forms():
    parsed = jvm.parse_file(
        """package com.example.alpha
import com.example.beta.Beta
import com.example.beta._
import com.example.beta.{Beta, Other}
case class Alpha(n: Int)
sealed trait Trait
object Registry
type Alias = Int
def helper(): Unit = ()
""",
        "scala",
    )
    assert parsed.declared == ["Alpha", "Trait", "Registry", "Alias", "helper"]
    assert [plain for _, plain in parsed.imports] == [True, False, False]


def test_jvm_comments_annotations_and_partial_packages():
    parsed = jvm.parse_file(
        'package p\nclass A {\n val s = "a/*b"\n}\nsealed class B', "scala"
    )
    assert parsed.declared == ["A", "B"]
    assert jvm.strip_annotations("@Foo(a(b)) class X") == "class X"
    assert jvm.strip_annotations("@Foo() class X") == "class X"
    block = jvm.parse_file("package com.example {\nclass A\n}", "java")
    assert block.package is None and not block.declared
    partial = jvm.parse_file(
        "package cats\npackage object data extends Base {\ntype X = Y\n}", "scala"
    )
    assert partial.partial == ["cats.data"]


def test_jvm_facts_resolve_and_mark_missing_types(tmp_path):
    source = tmp_path / "src/main/java/a/A.java"
    target = tmp_path / "src/main/java/b/B.java"
    source.parent.mkdir(parents=True)
    target.parent.mkdir(parents=True)
    source.write_text("package a;\nimport b.B;\nimport a.Missing;\nclass A {}")
    target.write_text("package b;\nclass B {}")
    files = [
        FileRow(1, "A.java", "src/main/java/a/A.java", source),
        FileRow(2, "B.java", "src/main/java/b/B.java", target),
    ]
    out = jvm.facts(
        FactInput(files, [ImportRow(1, 1, "b/B"), ImportRow(2, 1, "a/Missing")], [])
    )
    assert [(f.to_unit, f.certainty) for f in out] == [
        ("src/main/java/b", "certified"),
        (None, "missing"),
    ]


def test_csharp_plain_usings_resolve_project_namespaces(tmp_path):
    app = tmp_path / "App"
    lib = tmp_path / "Lib"
    app.mkdir()
    lib.mkdir()
    (app / "App.csproj").write_text("")
    (lib / "Lib.csproj").write_text("")
    source = app / "A.cs"
    target = lib / "B.cs"
    source.write_text("using Lib;\nnamespace App;\nclass A {}")
    target.write_text("namespace Lib;\nclass B {}")
    files = [
        FileRow(1, "A.cs", "App/A.cs", source),
        FileRow(2, "B.cs", "Lib/B.cs", target),
    ]
    out = csharp_swift.facts(FactInput(files, [ImportRow(1, 1, "Lib")], []))
    assert len(out) == 1 and out[0].to_unit == "Lib"


def test_swiftpm_imports_resolve_between_targets(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "Package.swift").write_text(
        'targets: [.target(name: "One"), .target(name: "Two")]'
    )
    one = package / "Sources/One/A.swift"
    two = package / "Sources/Two/B.swift"
    one.parent.mkdir(parents=True)
    two.parent.mkdir(parents=True)
    one.write_text("import Two\n")
    two.write_text("public struct B {}\n")
    files = [
        FileRow(1, "A.swift", "pkg/Sources/One/A.swift", one),
        FileRow(2, "B.swift", "pkg/Sources/Two/B.swift", two),
    ]
    out = csharp_swift.facts(FactInput(files, [ImportRow(1, 1, "Two")], []))
    assert len(out) == 1 and out[0].to_unit == "pkg/Sources/Two"


def test_xcode_targets_resolve_group_paths_and_build_settings(tmp_path):
    root = tmp_path
    project = root / "Demo.xcodeproj"
    project.mkdir()
    (root / "Sources/A").mkdir(parents=True)
    (root / "Sources/B").mkdir(parents=True)
    a = root / "Sources/A/A.swift"
    b = root / "Sources/B/B.swift"
    a.write_text("import Bee\n")
    b.write_text("public struct B {}\n")
    (project / "project.pbxproj").write_text("""{
      objects = {
        P = { isa = PBXProject; mainGroup = G; };
        G = { isa = PBXGroup; children = (RA, RB, ); };
        RA = { isa = PBXFileReference; lastKnownFileType = sourcecode.swift; \
path = Sources/A/A.swift; sourceTree = SOURCE_ROOT; };
        RB = { isa = PBXFileReference; lastKnownFileType = sourcecode.swift; \
path = Sources/B/B.swift; sourceTree = SOURCE_ROOT; };
        BA = { isa = PBXBuildFile; fileRef = RA; };
        BB = { isa = PBXBuildFile; fileRef = RB; };
        PA = { isa = PBXSourcesBuildPhase; files = (BA, ); };
        PB = { isa = PBXSourcesBuildPhase; files = (BB, ); };
        CA = { isa = XCBuildConfiguration; buildSettings = { PRODUCT_MODULE_NAME = \
App; }; };
        CB = { isa = XCBuildConfiguration; buildSettings = { PRODUCT_MODULE_NAME = \
Bee; }; };
        LA = { isa = XCConfigurationList; buildConfigurations = (CA, ); };
        LB = { isa = XCConfigurationList; buildConfigurations = (CB, ); };
        TA = { isa = PBXNativeTarget; name = App; buildPhases = (PA, ); \
buildConfigurationList = LA; };
        TB = { isa = PBXNativeTarget; name = Bee; buildPhases = (PB, ); \
buildConfigurationList = LB; };
      };
    }""")
    rows = [
        FileRow(1, "A.swift", "Sources/A/A.swift", a),
        FileRow(2, "B.swift", "Sources/B/B.swift", b),
    ]
    out = csharp_swift.facts(FactInput(rows, [ImportRow(1, 1, "Bee")], []))
    assert len(out) == 1 and out[0].to_unit == "Sources/B"


def test_xcode_common_directory_keeps_lexical_symlink_path(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "A.swift").write_text("import Bee\n")
    root = tmp_path / "repo"
    root.mkdir()
    (root / "Sources").mkdir()
    (root / "Sources" / "Alias.swift").symlink_to(outside / "A.swift")

    relative = csharp_swift.common_dir_relative(
        [root / "Sources" / "Alias.swift"], root
    )

    assert relative == "Sources"


def test_jvm_file_annotations_and_scoped_declarations():
    parsed = jvm.parse_file(
        """@file:JvmName("Util")
@file:Suppress("lint")
package com.example.alpha
import com.example.beta.Beta
internal val name = 1
""".replace("\n+", "\n"),
        "kotlin",
    )
    assert parsed.package == "com.example.alpha"
    assert parsed.declared == ["name"] and len(parsed.imports) == 1
    parsed = jvm.parse_file(
        "package p\nprivate[alpha] class Hidden\nprotected[this] trait Guarded", "scala"
    )
    assert parsed.declared == ["Hidden", "Guarded"]


def test_jvm_generic_receiver_function_names():
    parsed = jvm.parse_file(
        """package p
internal fun <T : Any, S : T?> ExpressionWithColumnType<in S>.min(): Min<T, S> = \
Min(this)
internal fun Map<String, String>.commonToHeaders(): Headers = Headers()
""".replace("\n+", "\n"),
        "kotlin",
    )
    assert parsed.declared == ["min", "commonToHeaders"]


def test_jvm_code_lines_split_only_on_newlines():
    assert jvm.code_lines("class A\u2028class B\rclass C\n") == [
        "class A\u2028class B\rclass C",
    ]


def test_jvm_missing_does_not_certify_values_or_partial_packages():
    parsed = jvm.parse_file(
        "package p\npackage object hidden {\n type X = Int\n}", "scala"
    )
    assert parsed.partial == ["p.hidden"]
    assert jvm.split_specifier("p/lowercase") == ("p", "lowercase")
    assert jvm.split_specifier("p/Bad-Name") is None
