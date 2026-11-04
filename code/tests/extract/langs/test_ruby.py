from varde_code.extract import extract_file, tables_for
from varde_code.model import EntityKind


def test_ruby_tables_and_entities():
    tables = tables_for("ruby")
    assert tables.function_scopes == frozenset({"method", "singleton_method"})
    assert tables.type_scopes == frozenset({"class", "module", "singleton_class"})
    output = extract_file(
        "sample.rb",
        'require "json"\nmodule Shared; end\nclass Worker < Base\n'
        "  include Shared\n  attr_accessor :value\n"
        "  def self.run(input, option = 1, key:, *rest, **extra, &block)\n"
        "    result, @cached = input.upcase, 2\n"
        '    if input && option\n      raise ArgumentError, "bad"\n'
        '    elsif option\n      get "/items" do\n        json({})\n      end\n'
        "    else\n      result = nil\n    end\n"
        "    begin\n      work\n    rescue IOError => error\n"
        "      fail error\n    end\n"
        "  end\nend\n",
        "ruby",
    )
    pairs = {(entity.kind, entity.name) for entity in output.entities}
    assert (EntityKind.IMPORT, "json") in pairs
    assert (EntityKind.INTERFACE, "Shared") in pairs
    assert (EntityKind.CLASS, "Worker") in pairs
    assert (EntityKind.EXTENDS, "Base") in pairs
    assert (EntityKind.IMPLEMENTS, "Shared") in pairs
    assert (EntityKind.FUNCTION, "run") in pairs
    assert (EntityKind.PARAMETER, "input") in pairs
    assert (EntityKind.PARAMETER, "option") in pairs
    assert (EntityKind.VARIABLE, "@cached") in pairs
    assert (EntityKind.VARIABLE, "value") in pairs
    assert (EntityKind.MEMBER_ACCESS, "upcase") in pairs
    assert (EntityKind.THROW, "ArgumentError") in pairs
    assert (EntityKind.CATCH, "error") in pairs
    assert (EntityKind.CONTROL_FLOW, "logical_and") in pairs
    assert (EntityKind.ROUTE, "get") in pairs
    assert (EntityKind.RESPONSE, "json") in pairs


def test_ruby_require_and_raise_are_not_plain_calls():
    entities = extract_file(
        "sample.rb", 'require_relative "helper"\nraise Error\n', "ruby"
    ).entities
    pairs = {(entity.kind, entity.name) for entity in entities}
    assert (EntityKind.IMPORT, "helper") in pairs
    assert (EntityKind.THROW, "Error") in pairs
    assert (EntityKind.CALL, "require_relative") not in pairs
    assert (EntityKind.CALL, "raise") not in pairs
