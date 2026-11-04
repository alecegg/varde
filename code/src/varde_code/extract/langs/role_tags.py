"""Shared role tag rules and matcher for language entrypoint signals."""

from __future__ import annotations

import re
from dataclasses import dataclass

from varde_code.model import RoleTag


@dataclass(frozen=True)
class RoleTagRule:
    decorator: str | None = None
    base_class: str | None = None
    path_glob: str | None = None
    role: RoleTag = RoleTag.ROUTE_HANDLER


def _rules(
    rows: tuple[tuple[str | None, str | None, str | None, RoleTag], ...],
) -> tuple[RoleTagRule, ...]:
    return tuple(RoleTagRule(*row) for row in rows)


PYTHON_RULES = _rules(
    (
        ("*.route", None, None, RoleTag.ROUTE_HANDLER),
        ("*.get", None, None, RoleTag.ROUTE_HANDLER),
        ("*.post", None, None, RoleTag.ROUTE_HANDLER),
        ("*.put", None, None, RoleTag.ROUTE_HANDLER),
        ("*.delete", None, None, RoleTag.ROUTE_HANDLER),
        ("*.patch", None, None, RoleTag.ROUTE_HANDLER),
        ("*.websocket", None, None, RoleTag.ROUTE_HANDLER),
        ("api_view", None, None, RoleTag.ROUTE_HANDLER),
        (None, "APIView", None, RoleTag.ROUTE_HANDLER),
        (None, "GenericAPIView", None, RoleTag.ROUTE_HANDLER),
        (None, "ViewSet", None, RoleTag.ROUTE_HANDLER),
        (None, "ModelViewSet", None, RoleTag.ROUTE_HANDLER),
        (None, "GenericViewSet", None, RoleTag.ROUTE_HANDLER),
        ("*.middleware", None, None, RoleTag.MIDDLEWARE),
        ("celery.task", None, None, RoleTag.BACKGROUND_JOB),
        ("task", None, None, RoleTag.BACKGROUND_JOB),
        ("shared_task", None, None, RoleTag.BACKGROUND_JOB),
        ("*.task", None, None, RoleTag.BACKGROUND_JOB),
        ("click.command", None, None, RoleTag.CLI_COMMAND),
        ("command", None, None, RoleTag.CLI_COMMAND),
    )
)

JAVA_RULES = _rules(
    (
        ("GetMapping", None, None, RoleTag.ROUTE_HANDLER),
        ("PostMapping", None, None, RoleTag.ROUTE_HANDLER),
        ("PutMapping", None, None, RoleTag.ROUTE_HANDLER),
        ("DeleteMapping", None, None, RoleTag.ROUTE_HANDLER),
        ("PatchMapping", None, None, RoleTag.ROUTE_HANDLER),
        ("RequestMapping", None, None, RoleTag.ROUTE_HANDLER),
        ("Controller", None, None, RoleTag.ROUTE_HANDLER),
        ("RestController", None, None, RoleTag.ROUTE_HANDLER),
        ("Path", None, None, RoleTag.ROUTE_HANDLER),
        ("GET", None, None, RoleTag.ROUTE_HANDLER),
        ("POST", None, None, RoleTag.ROUTE_HANDLER),
        ("PUT", None, None, RoleTag.ROUTE_HANDLER),
        ("DELETE", None, None, RoleTag.ROUTE_HANDLER),
        ("PATCH", None, None, RoleTag.ROUTE_HANDLER),
        ("HEAD", None, None, RoleTag.ROUTE_HANDLER),
        ("OPTIONS", None, None, RoleTag.ROUTE_HANDLER),
        ("Scheduled", None, None, RoleTag.BACKGROUND_JOB),
        ("EventListener", None, None, RoleTag.EVENT_LISTENER),
        ("KafkaListener", None, None, RoleTag.EVENT_LISTENER),
        ("RabbitListener", None, None, RoleTag.EVENT_LISTENER),
        ("JmsListener", None, None, RoleTag.EVENT_LISTENER),
        ("MessageMapping", None, None, RoleTag.EVENT_LISTENER),
    )
)

KOTLIN_RULES = _rules(
    (
        ("RestController", None, None, RoleTag.ROUTE_HANDLER),
        ("Controller", None, None, RoleTag.ROUTE_HANDLER),
        ("RequestMapping", None, None, RoleTag.ROUTE_HANDLER),
        ("GetMapping", None, None, RoleTag.ROUTE_HANDLER),
        ("PostMapping", None, None, RoleTag.ROUTE_HANDLER),
        ("PutMapping", None, None, RoleTag.ROUTE_HANDLER),
        ("DeleteMapping", None, None, RoleTag.ROUTE_HANDLER),
        ("PatchMapping", None, None, RoleTag.ROUTE_HANDLER),
        ("Get", None, None, RoleTag.ROUTE_HANDLER),
        ("Post", None, None, RoleTag.ROUTE_HANDLER),
        ("Put", None, None, RoleTag.ROUTE_HANDLER),
        ("Delete", None, None, RoleTag.ROUTE_HANDLER),
        ("Patch", None, None, RoleTag.ROUTE_HANDLER),
        ("Scheduled", None, None, RoleTag.BACKGROUND_JOB),
        ("EventListener", None, None, RoleTag.EVENT_LISTENER),
        ("KafkaListener", None, None, RoleTag.EVENT_LISTENER),
        ("RabbitListener", None, None, RoleTag.EVENT_LISTENER),
    )
)

SCALA_RULES = _rules(
    (
        ("*.get", None, None, RoleTag.ROUTE_HANDLER),
        ("*.post", None, None, RoleTag.ROUTE_HANDLER),
        ("*.put", None, None, RoleTag.ROUTE_HANDLER),
        ("*.delete", None, None, RoleTag.ROUTE_HANDLER),
        ("*.patch", None, None, RoleTag.ROUTE_HANDLER),
        (None, "BaseController", None, RoleTag.ROUTE_HANDLER),
        (None, "AbstractController", None, RoleTag.ROUTE_HANDLER),
        (None, "InjectedController", None, RoleTag.ROUTE_HANDLER),
    )
)

CS_RULES = _rules(
    (
        ("ApiController", None, None, RoleTag.ROUTE_HANDLER),
        ("Route", None, None, RoleTag.ROUTE_HANDLER),
        ("HttpGet", None, None, RoleTag.ROUTE_HANDLER),
        ("HttpPost", None, None, RoleTag.ROUTE_HANDLER),
        ("HttpPut", None, None, RoleTag.ROUTE_HANDLER),
        ("HttpDelete", None, None, RoleTag.ROUTE_HANDLER),
        ("HttpPatch", None, None, RoleTag.ROUTE_HANDLER),
        ("HttpHead", None, None, RoleTag.ROUTE_HANDLER),
        ("HttpOptions", None, None, RoleTag.ROUTE_HANDLER),
        (None, "Controller", None, RoleTag.ROUTE_HANDLER),
        (None, "ControllerBase", None, RoleTag.ROUTE_HANDLER),
        (None, "IHostedService", None, RoleTag.BACKGROUND_JOB),
        (None, "BackgroundService", None, RoleTag.BACKGROUND_JOB),
    )
)

TS_RULES = _rules(
    (
        ("Get", None, None, RoleTag.ROUTE_HANDLER),
        ("Post", None, None, RoleTag.ROUTE_HANDLER),
        ("Put", None, None, RoleTag.ROUTE_HANDLER),
        ("Delete", None, None, RoleTag.ROUTE_HANDLER),
        ("Patch", None, None, RoleTag.ROUTE_HANDLER),
        ("Head", None, None, RoleTag.ROUTE_HANDLER),
        ("Options", None, None, RoleTag.ROUTE_HANDLER),
        ("All", None, None, RoleTag.ROUTE_HANDLER),
        ("Sse", None, None, RoleTag.ROUTE_HANDLER),
        ("Controller", None, None, RoleTag.ROUTE_HANDLER),
        ("MessagePattern", None, None, RoleTag.EVENT_LISTENER),
        ("EventPattern", None, None, RoleTag.EVENT_LISTENER),
        ("SubscribeMessage", None, None, RoleTag.EVENT_LISTENER),
        ("Injectable", "NestMiddleware", None, RoleTag.MIDDLEWARE),
        ("Component", None, None, RoleTag.PAGE_COMPONENT),
        ("Cron", None, None, RoleTag.BACKGROUND_JOB),
        ("OnEvent", None, None, RoleTag.EVENT_LISTENER),
        (None, None, "**/pages/**", RoleTag.PAGE_COMPONENT),
    )
)

TSX_RULES = _rules(
    (
        ("Component", None, None, RoleTag.PAGE_COMPONENT),
        (None, None, "**/pages/**", RoleTag.PAGE_COMPONENT),
        (None, None, "**/app/**", RoleTag.PAGE_COMPONENT),
    )
)

JS_RULES = _rules(((None, None, "**/pages/**", RoleTag.PAGE_COMPONENT),))

RUBY_RULES = _rules(
    (
        (None, "ApplicationController", None, RoleTag.ROUTE_HANDLER),
        (None, "ActionController::Base", None, RoleTag.ROUTE_HANDLER),
        (None, "ActionController::API", None, RoleTag.ROUTE_HANDLER),
        (None, "*Controller", None, RoleTag.ROUTE_HANDLER),
        (None, "ApplicationJob", None, RoleTag.BACKGROUND_JOB),
        (None, "ActiveJob::Base", None, RoleTag.BACKGROUND_JOB),
        (None, "Sidekiq::Job", None, RoleTag.BACKGROUND_JOB),
        (None, "Sidekiq::Worker", None, RoleTag.BACKGROUND_JOB),
        (None, "ApplicationCable::Channel", None, RoleTag.EVENT_LISTENER),
    )
)

PHP_RULES = _rules(
    (
        ("Route", None, None, RoleTag.ROUTE_HANDLER),
        ("Get", None, None, RoleTag.ROUTE_HANDLER),
        ("Post", None, None, RoleTag.ROUTE_HANDLER),
        ("Put", None, None, RoleTag.ROUTE_HANDLER),
        ("Delete", None, None, RoleTag.ROUTE_HANDLER),
        ("Patch", None, None, RoleTag.ROUTE_HANDLER),
        ("AsMessageHandler", None, None, RoleTag.EVENT_LISTENER),
        ("AsCommand", None, None, RoleTag.CLI_COMMAND),
        (None, "AbstractController", None, RoleTag.ROUTE_HANDLER),
        (None, "Controller", None, RoleTag.ROUTE_HANDLER),
        (None, "Command", None, RoleTag.CLI_COMMAND),
    )
)


def _last_segment(name: str) -> str:
    return re.split(r"[./:]", name)[-1]


def _matches_qualified(wanted: str, signal: str | None) -> bool:
    return (
        not any(separator in wanted for separator in (".", "/", ":"))
        and signal is not None
        and _last_segment(signal) == wanted
    )


def _glob_match(pattern: str, text: str) -> bool:
    """Match the limited `*` and `**` glob syntax used by these tables."""

    def match(pattern_index: int, text_index: int) -> bool:
        if pattern_index == len(pattern):
            return text_index == len(text)
        if pattern[pattern_index] == "*":
            double = (
                pattern_index + 1 < len(pattern) and pattern[pattern_index + 1] == "*"
            )
            rest = pattern_index + (2 if double else 1)
            if double and rest < len(pattern) and pattern[rest] == "/":
                rest += 1
            end = len(text)
            if not double:
                slash = text.find("/", text_index)
                if slash >= 0:
                    end = slash
            return any(match(rest, offset) for offset in range(text_index, end + 1))
        return (
            text_index < len(text)
            and pattern[pattern_index] == text[text_index]
            and match(pattern_index + 1, text_index + 1)
        )

    return match(0, 0)


def match_role_tag(
    rules: tuple[RoleTagRule, ...] | list[RoleTagRule],
    decorator: str | None = None,
    base_class: str | None = None,
    path: str | None = None,
) -> RoleTag | None:
    """Return the first role whose declared signals all match."""
    for rule in rules:
        decorator_ok = rule.decorator is None
        if rule.decorator is not None:
            if rule.decorator.startswith("*."):
                decorator_ok = (
                    decorator is not None
                    and decorator.rsplit(".", 1)[-1] == rule.decorator[2:]
                )
            else:
                decorator_ok = decorator == rule.decorator or _matches_qualified(
                    rule.decorator, decorator
                )

        base_class_ok = rule.base_class is None
        if rule.base_class is not None:
            if rule.base_class.startswith("*"):
                suffix = rule.base_class[1:]
                base_class_ok = base_class is not None and _last_segment(
                    base_class
                ).endswith(suffix)
            else:
                base_class_ok = base_class == rule.base_class or _matches_qualified(
                    rule.base_class, base_class
                )

        path_ok = rule.path_glob is None or (
            path is not None and _glob_match(rule.path_glob, path)
        )
        if decorator_ok and base_class_ok and path_ok:
            return rule.role
    return None
