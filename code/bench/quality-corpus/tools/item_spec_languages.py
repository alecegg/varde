"""Tree-sitter node tables shared by the category (b) item checks."""

from __future__ import annotations

from dataclasses import dataclass

VERSIONS = ("sensible", "monolith", "tiny", "padded", "sizematched", "namematched")
# Optional preference-style versions. They are behaviour-identical to sensible and
# judged as good in a different style, so they are never quality deltas.
ALT_VERSIONS = ("alt-pipeline", "alt-table", "alt-class")
EXTENSIONS = {
    "python": ".py",
    "typescript": ".ts",
    "java": ".java",
    "csharp": ".cs",
    "go": ".go",
    "rust": ".rs",
    "cpp": ".cpp",
}

FUNCTION_NODES: dict[str, frozenset[str]] = {
    "typescript": frozenset(
        {
            "function_declaration",
            "generator_function_declaration",
            "method_definition",
            "arrow_function",
            "function_expression",
        }
    ),
    "java": frozenset(
        {"method_declaration", "constructor_declaration", "lambda_expression"}
    ),
    "csharp": frozenset(
        {
            "method_declaration",
            "local_function_statement",
            "lambda_expression",
            "anonymous_method_expression",
        }
    ),
    "go": frozenset({"function_declaration", "method_declaration", "func_literal"}),
    "rust": frozenset({"function_item", "closure_expression"}),
    "cpp": frozenset({"function_definition", "lambda_expression"}),
}

CALL_NODES: dict[str, frozenset[str]] = {
    "typescript": frozenset({"call_expression", "new_expression"}),
    "java": frozenset({"method_invocation", "object_creation_expression"}),
    "csharp": frozenset({"invocation_expression", "object_creation_expression"}),
    "go": frozenset({"call_expression"}),
    "rust": frozenset({"call_expression", "macro_invocation"}),
    "cpp": frozenset({"call_expression", "new_expression"}),
}


@dataclass(frozen=True)
class Cognitive:
    """Per-language node types for one cognitive complexity implementation."""

    branches: frozenset[str]
    boolean: frozenset[str]
    operators: frozenset[str]
    else_nodes: frozenset[str] = frozenset()
    else_field: str = ""


BOOLEAN_OPERATORS = frozenset({"&&", "||"})

COGNITIVE: dict[str, Cognitive] = {
    "typescript": Cognitive(
        branches=frozenset(
            {
                "if_statement",
                "for_statement",
                "for_in_statement",
                "while_statement",
                "do_statement",
                "switch_statement",
                "ternary_expression",
                "catch_clause",
            }
        ),
        boolean=frozenset({"binary_expression"}),
        operators=BOOLEAN_OPERATORS,
        else_nodes=frozenset({"else_clause"}),
    ),
    "java": Cognitive(
        branches=frozenset(
            {
                "if_statement",
                "for_statement",
                "enhanced_for_statement",
                "while_statement",
                "do_statement",
                "switch_statement",
                "switch_expression",
                "ternary_expression",
                "catch_clause",
            }
        ),
        boolean=frozenset({"binary_expression"}),
        operators=BOOLEAN_OPERATORS,
        else_field="alternative",
    ),
    "csharp": Cognitive(
        branches=frozenset(
            {
                "if_statement",
                "for_statement",
                "foreach_statement",
                "while_statement",
                "do_statement",
                "switch_statement",
                "switch_expression",
                "conditional_expression",
                "catch_clause",
            }
        ),
        boolean=frozenset({"binary_expression"}),
        operators=BOOLEAN_OPERATORS,
        else_field="alternative",
    ),
    "go": Cognitive(
        branches=frozenset(
            {
                "if_statement",
                "for_statement",
                "expression_switch_statement",
                "type_switch_statement",
                "select_statement",
            }
        ),
        boolean=frozenset({"binary_expression"}),
        operators=BOOLEAN_OPERATORS,
        else_field="alternative",
    ),
    "rust": Cognitive(
        branches=frozenset(
            {
                "if_expression",
                "for_expression",
                "while_expression",
                "loop_expression",
                "match_expression",
            }
        ),
        boolean=frozenset({"binary_expression"}),
        operators=BOOLEAN_OPERATORS,
        else_nodes=frozenset({"else_clause"}),
    ),
    "cpp": Cognitive(
        branches=frozenset(
            {
                "if_statement",
                "for_statement",
                "range_based_for_statement",
                "while_statement",
                "do_statement",
                "switch_statement",
                "conditional_expression",
                "catch_clause",
            }
        ),
        boolean=frozenset({"binary_expression"}),
        operators=BOOLEAN_OPERATORS,
        else_nodes=frozenset({"else_clause"}),
    ),
}

RETURN_TYPE_FIELDS = {
    "typescript": "return_type",
    "java": "type",
    "csharp": "type",
    "go": "result",
    "rust": "return_type",
    "cpp": "type",
}
