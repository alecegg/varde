"""TSX uses TypeScript extraction rules with an independent language table."""

from __future__ import annotations

from . import ts
from .base import LanguageTables

BACKEND = "tree-sitter"
FUNCTION_SCOPES = ts.FUNCTION_SCOPES
TYPE_SCOPES = ts.TYPE_SCOPES
REQUIRED_KINDS = ts.REQUIRED_KINDS
FLOW_NAME_ROLES = ts.FLOW_NAME_ROLES
LANG = LanguageTables(
    function_scopes=FUNCTION_SCOPES,
    type_scopes=TYPE_SCOPES,
    required_kinds=REQUIRED_KINDS,
    flow_roles=FLOW_NAME_ROLES,
    visit_node=ts.LANG.visit_node,
    function_name=ts.LANG.function_name,
    type_name=ts.LANG.type_name,
    type_kinds=ts.TYPE_CONTEXT_KINDS,
)
