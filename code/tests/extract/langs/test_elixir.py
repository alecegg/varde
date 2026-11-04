from varde_code.extract import extract_file
from varde_code.extract.langs import tables_for
from varde_code.model import EntityKind


def test_elixir_tables_and_entities():
    tables = tables_for("elixir")
    assert tables.function_scopes == frozenset()
    assert tables.type_scopes == frozenset()
    assert EntityKind.FUNCTION in tables.required_kinds
    assert EntityKind.INTERFACE in tables.required_kinds

    output = extract_file(
        "sample.ex",
        """defmodule Sample do
  import Enum
  @answer 42
  def run(input) do
    value = Enum.map(input, &(&1 + 1))
    if value, do: raise("bad")
    value
  end
end
""",
        "elixir",
    )
    pairs = {(entity.kind, entity.name) for entity in output.entities}
    assert (EntityKind.CLASS, "Sample") in pairs
    assert (EntityKind.IMPORT, "Enum") in pairs
    assert (EntityKind.VARIABLE, "@answer") in pairs
    assert (EntityKind.FUNCTION, "run") in pairs
    assert (EntityKind.PARAMETER, "input") in pairs
    assert (EntityKind.MEMBER_ACCESS, "map") in pairs
    assert (EntityKind.CONTROL_FLOW, "if") in pairs
    assert any(kind == EntityKind.LITERAL for kind, _ in pairs)


def test_elixir_protocol_route_and_patterns():
    output = extract_file(
        "sample.ex",
        """defprotocol Size do
  def size(value)
end
defmodule Router do
  get "/items", ItemController, :index
  def choose({left, right}), do: left || right
end
""",
        "elixir",
    )
    pairs = {(entity.kind, entity.name) for entity in output.entities}
    assert (EntityKind.INTERFACE, "Size") in pairs
    assert (EntityKind.ROUTE, "get") in pairs
    assert (EntityKind.FUNCTION, "choose") in pairs
    assert (EntityKind.PARAMETER, "left") in pairs
    assert (EntityKind.CONTROL_FLOW, "logical_or") in pairs


def test_elixir_clause_groups_recursion_and_rescue_branches():
    output = extract_file(
        "sample.ex",
        """defmodule Sample do
  def choose(0), do: :done
  def choose(value), do: choose(value - 1)
  def load(value) do
    if value do
      value
    else
      nil
    end
    try do
      run(value)
    rescue
      error -> error
    end
  end
end
""",
        "elixir",
    )
    flow = [
        entity.name
        for entity in output.entities
        if entity.kind == EntityKind.CONTROL_FLOW
    ]
    catches = [
        entity.name for entity in output.entities if entity.kind == EntityKind.CATCH
    ]
    assert flow.count("elixir_unknown_multi_clause_grouping") == 2
    assert flow.count("recursive_call") == 1
    assert "else_branch" in flow
    assert catches == ["catch_clause"]
