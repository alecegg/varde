"""Shared data structures for source extraction and graph resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum

from tree_sitter import Node


class EntityKind(IntEnum):
    FUNCTION = 0
    CLASS = 1
    INTERFACE = 2
    VARIABLE = 3
    PARAMETER = 4
    EXPORT = 5
    CALL = 6
    LITERAL = 7
    MEMBER_ACCESS = 8
    IMPORT = 9
    CATCH = 10
    THROW = 11
    CONTROL_FLOW = 12
    ROUTE = 13
    RESPONSE = 14
    EXTENDS = 15
    IMPLEMENTS = 16
    DECORATOR = 17
    TYPE_REF = 18
    CALLABLE_BOUNDARY = 19

    def as_i64(self) -> int:
        return int(self)

    def as_str(self) -> str:
        return self.name.lower()

    @classmethod
    def from_i64(cls, value: int) -> EntityKind | None:
        try:
            return cls(value)
        except ValueError:
            return None


class SymbolKind(IntEnum):
    BINDING = 0
    REFERENCE = 1

    def as_i64(self) -> int:
        return int(self)

    def as_str(self) -> str:
        return self.name.lower()

    @classmethod
    def from_i64(cls, value: int) -> SymbolKind | None:
        try:
            return cls(value)
        except ValueError:
            return None


class EdgeKind(IntEnum):
    CALL = 0
    IMPORT = 1
    EXTENDS = 2
    IMPLEMENTS = 3

    def as_i64(self) -> int:
        return int(self)

    def as_str(self) -> str:
        return self.name.lower()

    @classmethod
    def from_i64(cls, value: int) -> EdgeKind | None:
        try:
            return cls(value)
        except ValueError:
            return None


class RoleTag(StrEnum):
    ROUTE_HANDLER = "route_handler"
    PAGE_COMPONENT = "page_component"
    CLI_COMMAND = "cli_command"
    BACKGROUND_JOB = "background_job"
    EVENT_LISTENER = "event_listener"
    MIDDLEWARE = "middleware"
    PROCESS_MAIN = "process_main"


@dataclass(frozen=True)
class Span:
    start_byte: int
    end_byte: int
    start_line: int
    start_col: int
    end_line: int
    end_col: int


@dataclass(frozen=True)
class FileMeta:
    mtime: int
    size: int
    content_hash: str


@dataclass
class Entity:
    kind: EntityKind
    name: str
    file_id: int
    span: Span
    enclosing_function: str | None = None
    method: str | None = None
    path: str | None = None
    status: str | None = None
    body_shape: str | None = None
    body_minhash: list[int] | None = None
    is_async: bool | None = None
    is_test: bool = False
    owner_type: str | None = None


@dataclass
class Symbol:
    kind: SymbolKind
    name: str
    file_id: int
    span: Span


@dataclass(frozen=True)
class Diagnostic:
    file_id: int | None
    path: str
    message: str
    severity: str


@dataclass
class ExtractOutput:
    entities: list[Entity] = field(default_factory=list)
    symbols: list[Symbol] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    file_meta: list[FileMeta] = field(default_factory=list)


@dataclass(frozen=True)
class Community:
    id: int
    members: list[str]


def saturating_u32(value: int) -> int:
    return min(max(value, 0), 0xFFFFFFFF)


def span_of(node: Node) -> Span:
    """Build a Rust-compatible span from a tree-sitter node."""
    start = node.start_point
    end = node.end_point
    start_row, start_column = start
    end_row, end_column = end
    return Span(
        saturating_u32(node.start_byte),
        saturating_u32(node.end_byte),
        saturating_u32(start_row) + 1,
        saturating_u32(start_column),
        saturating_u32(end_row) + 1,
        saturating_u32(end_column),
    )
