from varde_code.extract.langs.role_tags import (
    CS_RULES,
    JAVA_RULES,
    JS_RULES,
    KOTLIN_RULES,
    PHP_RULES,
    PYTHON_RULES,
    RUBY_RULES,
    SCALA_RULES,
    TS_RULES,
    TSX_RULES,
    RoleTagRule,
    match_role_tag,
)
from varde_code.model import RoleTag


def test_python_framework_decorators_and_classes():
    for decorator in (
        "app.get",
        "router.post",
        "v1.put",
        "app.delete",
        "app.patch",
        "app.websocket",
        "admin_bp.route",
        "app.route",
        "api_view",
    ):
        assert (
            match_role_tag(PYTHON_RULES, decorator=decorator) is RoleTag.ROUTE_HANDLER
        )

    for base in ("APIView", "ModelViewSet", "GenericViewSet"):
        assert match_role_tag(PYTHON_RULES, base_class=base) is RoleTag.ROUTE_HANDLER
    for decorator in ("shared_task", "app.task", "celery.task"):
        assert (
            match_role_tag(PYTHON_RULES, decorator=decorator) is RoleTag.BACKGROUND_JOB
        )
    assert match_role_tag(PYTHON_RULES, decorator="staticmethod") is None
    assert match_role_tag(PYTHON_RULES, decorator="x.getter") is None
    assert match_role_tag(PYTHON_RULES, decorator="click.option") is None


def test_language_tables_match_web_framework_conventions():
    assert (
        match_role_tag(JAVA_RULES, decorator="RestController") is RoleTag.ROUTE_HANDLER
    )
    assert match_role_tag(JAVA_RULES, decorator="Scheduled") is RoleTag.BACKGROUND_JOB
    assert (
        match_role_tag(JAVA_RULES, decorator="KafkaListener") is RoleTag.EVENT_LISTENER
    )
    for decorator in (
        "GET",
        "POST",
        "PUT",
        "DELETE",
        "PATCH",
        "HEAD",
        "OPTIONS",
        "Path",
    ):
        assert match_role_tag(JAVA_RULES, decorator=decorator) is RoleTag.ROUTE_HANDLER

    for decorator in ("RestController", "GetMapping", "Get", "Post", "Patch"):
        assert (
            match_role_tag(KOTLIN_RULES, decorator=decorator) is RoleTag.ROUTE_HANDLER
        )
    assert (
        match_role_tag(KOTLIN_RULES, decorator="KafkaListener")
        is RoleTag.EVENT_LISTENER
    )

    for decorator in ("cask.get", "cask.post", "cask.put"):
        assert match_role_tag(SCALA_RULES, decorator=decorator) is RoleTag.ROUTE_HANDLER
    for decorator in (
        "HttpGet",
        "HttpPost",
        "HttpPut",
        "HttpDelete",
        "HttpPatch",
        "HttpHead",
        "HttpOptions",
    ):
        assert match_role_tag(CS_RULES, decorator=decorator) is RoleTag.ROUTE_HANDLER
    assert (
        match_role_tag(CS_RULES, base_class="ControllerBase") is RoleTag.ROUTE_HANDLER
    )
    assert (
        match_role_tag(CS_RULES, base_class="BackgroundService")
        is RoleTag.BACKGROUND_JOB
    )

    for decorator in (
        "Get",
        "Post",
        "Put",
        "Delete",
        "Patch",
        "Head",
        "Options",
        "All",
        "Sse",
    ):
        assert match_role_tag(TS_RULES, decorator=decorator) is RoleTag.ROUTE_HANDLER
    for decorator in ("MessagePattern", "EventPattern", "SubscribeMessage"):
        assert match_role_tag(TS_RULES, decorator=decorator) is RoleTag.EVENT_LISTENER
    assert (
        match_role_tag(TS_RULES, decorator="Injectable", base_class="NestMiddleware")
        is RoleTag.MIDDLEWARE
    )
    assert match_role_tag(TS_RULES, decorator="Injectable") is None
    assert match_role_tag(TS_RULES, base_class="NestMiddleware") is None


def test_path_conventions_and_ruby_base_classes():
    for rules in (TS_RULES, TSX_RULES, JS_RULES):
        assert (
            match_role_tag(rules, path="src/pages/index.ts") is RoleTag.PAGE_COMPONENT
        )
    assert match_role_tag(TSX_RULES, path="src/app/home.tsx") is RoleTag.PAGE_COMPONENT
    assert match_role_tag(TSX_RULES, path="src/lib/util.tsx") is None

    for base in (
        "Devise::SessionsController",
        "Admin::BaseController",
        "Api::V1::BaseController",
        "ApplicationController",
    ):
        assert match_role_tag(RUBY_RULES, base_class=base) is RoleTag.ROUTE_HANDLER
    assert match_role_tag(RUBY_RULES, base_class="SomeService") is None
    assert (
        match_role_tag(RUBY_RULES, base_class="ApplicationJob")
        is RoleTag.BACKGROUND_JOB
    )
    assert (
        match_role_tag(RUBY_RULES, base_class="Sidekiq::Job") is RoleTag.BACKGROUND_JOB
    )
    assert (
        match_role_tag(RUBY_RULES, base_class="ApplicationCable::Channel")
        is RoleTag.EVENT_LISTENER
    )


def test_php_attributes_and_qualified_signals():
    for decorator in ("Route", "Get", "Post", "Put", "Delete", "Patch"):
        assert match_role_tag(PHP_RULES, decorator=decorator) is RoleTag.ROUTE_HANDLER
    assert (
        match_role_tag(PHP_RULES, decorator="AsMessageHandler")
        is RoleTag.EVENT_LISTENER
    )
    assert match_role_tag(PHP_RULES, decorator="AsCommand") is RoleTag.CLI_COMMAND
    assert (
        match_role_tag(
            PHP_RULES,
            decorator="Symfony/Component/Routing/Annotation/Route",
        )
        is RoleTag.ROUTE_HANDLER
    )
    assert (
        match_role_tag(
            PHP_RULES,
            base_class="Symfony/Bundle/FrameworkBundle/Controller/AbstractController",
        )
        is RoleTag.ROUTE_HANDLER
    )
    assert match_role_tag(PHP_RULES, base_class="App/Http/MyController") is None
    assert (
        match_role_tag(JAVA_RULES, decorator="org.springframework.web.GetMapping")
        is RoleTag.ROUTE_HANDLER
    )
    assert (
        match_role_tag(RUBY_RULES, base_class="Api::ApplicationController")
        is RoleTag.ROUTE_HANDLER
    )


def test_rule_fields_are_conjunctive_and_missing_signals_do_not_match():
    rules = (RoleTagRule("Get", "ControllerBase", "**/api/**", RoleTag.ROUTE_HANDLER),)
    assert (
        match_role_tag(rules, "Get", "ControllerBase", "src/api/routes.py")
        is RoleTag.ROUTE_HANDLER
    )
    assert match_role_tag(rules, "Get", "ControllerBase", "src/lib/routes.py") is None
    assert match_role_tag(rules, "Get", None, "src/api/routes.py") is None
    assert match_role_tag(rules, None, "ControllerBase", "src/api/routes.py") is None
    assert match_role_tag(rules, "Get", "ControllerBase", None) is None


def test_path_glob_star_does_not_cross_directories():
    rules = (RoleTagRule(path_glob="src/*/pages/*.tsx", role=RoleTag.PAGE_COMPONENT),)
    assert (
        match_role_tag(rules, path="src/app/pages/home.tsx") is RoleTag.PAGE_COMPONENT
    )
    assert match_role_tag(rules, path="src/app/nested/pages/home.tsx") is None
