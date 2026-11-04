from varde_code.extract import extract_file
from varde_code.extract.langs import tables_for
from varde_code.model import EntityKind


def test_scala_tables_and_entities():
    tables = tables_for("scala")
    assert tables.function_scopes == frozenset(
        {"function_definition", "function_declaration"}
    )
    assert tables.type_scopes == frozenset(
        {"class_definition", "trait_definition", "object_definition"}
    )
    assert tables.function_name is not None
    assert tables.type_name is not None
    assert EntityKind.CALL in tables.required_kinds

    output = extract_file(
        "Sample.scala",
        """import scala.collection.mutable.{Map, Set}
@Controller
object Sample extends Base[Int] with Logging {
  val state = "ready"
  given ordering: Ordering[Int] = ???
  type Alias = List[Int]
  def run(input: Int): Int = {
    val saved = client.save(input)
    if (input > 0 && ready) throw new Error("bad") else return saved
  }
  try { run(1) } catch { case error: Exception => log(error) }
}
trait Worker { def work(): Int }
""",
        "scala",
    )
    pairs = {(entity.kind, entity.name) for entity in output.entities}
    assert (EntityKind.IMPORT, "scala/collection/mutable") in pairs
    assert (EntityKind.CLASS, "Sample") in pairs
    assert (EntityKind.INTERFACE, "Worker") in pairs
    assert (EntityKind.FUNCTION, "run") in pairs
    assert (EntityKind.FUNCTION, "work") in pairs
    assert (EntityKind.PARAMETER, "input") in pairs
    assert (EntityKind.VARIABLE, "saved") in pairs
    assert (EntityKind.VARIABLE, "ordering") in pairs
    assert (EntityKind.INTERFACE, "Alias") in pairs
    assert (EntityKind.CALL, "save") in pairs
    assert (EntityKind.MEMBER_ACCESS, "save") in pairs
    assert (EntityKind.EXTENDS, "Base") in pairs
    assert (EntityKind.IMPLEMENTS, "Logging") in pairs
    assert (EntityKind.CATCH, "error") in pairs
    assert (EntityKind.THROW, "Error") in pairs
    assert (EntityKind.DECORATOR, "Controller") in pairs
    assert (EntityKind.CONTROL_FLOW, "logical_and") in pairs


def test_scala_class_constructor_parameters_and_lambda_boundary():
    output = extract_file(
        "Sample.scala",
        "case class Point(x: Int, y: Int)\nobject O { val f = (x: Int) => x + 1 }\n",
        "scala",
    )
    pairs = {(entity.kind, entity.name) for entity in output.entities}
    assert (EntityKind.CLASS, "Point") in pairs
    assert (EntityKind.PARAMETER, "x") in pairs
    assert (EntityKind.PARAMETER, "y") in pairs
    assert (EntityKind.CALLABLE_BOUNDARY, "") in pairs
