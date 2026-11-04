from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest
from varde_data.config import DataConfig, load_data_config
from varde_data.errors import Invalid
from varde_data.open import (
    DOMAIN_REGISTRY,
    DomainRegistration,
    check_schema_version,
    open_data,
)


def test_queue_opens_at_current_schema_version(tmp_path: Path) -> None:
    from varde_data.queue_store import initialize

    initialize(tmp_path)

    queue = open_data(tmp_path, DataConfig()).queue

    assert queue is not None


def test_queue_rejects_version_newer_than_schema(tmp_path: Path) -> None:
    from varde_data.backends.sqlite.queue_schema import SCHEMA_VERSION

    version_path = tmp_path / ".cache" / "data" / "queue.version"
    version_path.parent.mkdir(parents=True)
    version_path.write_text(f"{SCHEMA_VERSION + 1}\n", encoding="ascii")

    with pytest.raises(
        Invalid,
        match=(
            f"store schema version {SCHEMA_VERSION + 1}.*supported version "
            f"{SCHEMA_VERSION}"
        ),
    ):
        _ = open_data(tmp_path, DataConfig()).queue


def test_registered_supported_versions_match_backend_schema_constants() -> None:
    from varde_data.backends.sqlite import queue_schema

    schema_constants = {"queue": queue_schema.SCHEMA_VERSION}
    for name, registration in DOMAIN_REGISTRY.items():
        if registration.supported_version is None:
            continue
        assert name in schema_constants, f"missing schema constant for {name}"
        assert registration.supported_version == schema_constants[name]


def test_schema_and_marker_versions_match_supported_version_checks(
    tmp_path: Path,
) -> None:
    from varde_data.backends.sqlite.messages import SCHEMA_VERSION as MESSAGE_VERSION
    from varde_data.backends.sqlite.queue_schema import (
        QUEUE_MARKER_VERSION,
    )
    from varde_data.backends.sqlite.queue_schema import (
        SCHEMA_VERSION as QUEUE_VERSION,
    )
    from varde_data.store_mode import (
        STORE_MODE_MARKER_VERSION,
        StoreModeInvalid,
        parse_store_mode_record,
    )

    assert MESSAGE_VERSION == 5
    assert STORE_MODE_MARKER_VERSION == 1
    assert DOMAIN_REGISTRY["queue"].supported_version == QUEUE_VERSION == 4
    assert QUEUE_MARKER_VERSION == QUEUE_VERSION
    from varde_data.role_queue_merge import QUEUE_VERSION_MARKER

    assert Path(".cache/data/queue.version") == QUEUE_VERSION_MARKER
    version_path = tmp_path / "messages.version"
    version_path.write_text(f"{MESSAGE_VERSION + 1}\n", encoding="ascii")
    with pytest.raises(Invalid, match="newer than supported"):
        check_schema_version(version_path, MESSAGE_VERSION)
    with pytest.raises(StoreModeInvalid, match="marker version"):
        parse_store_mode_record(
            '{"version":2,"primary":"files","mirror":"none",'
            '"import_verified_at":"2026-10-23T00:00:00Z","generation":1}'
        )


def test_config_defaults_and_environment_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("VARDE_DATA_MESSAGES_BACKEND", raising=False)
    assert load_data_config(tmp_path).backends == {}

    (tmp_path / "data.toml").write_text(
        '[domains]\nmessages = "memory"\n', encoding="utf-8"
    )
    monkeypatch.setenv("VARDE_DATA_MESSAGES_BACKEND", "files")
    assert load_data_config(tmp_path) == DataConfig(backends={"messages": "files"})


def test_config_rejects_unknown_backend(tmp_path: Path) -> None:
    (tmp_path / "data.toml").write_text(
        '[domains]\nmessages = "redis"\n', encoding="utf-8"
    )
    with pytest.raises(Invalid, match="unknown backend"):
        load_data_config(tmp_path)


def test_open_data_imports_domains_lazily(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module_name = "varde_data.testing_fixture"
    sys.modules.pop(module_name, None)
    monkeypatch.setitem(
        __import__("varde_data.open", fromlist=["DOMAIN_REGISTRY"]).DOMAIN_REGISTRY,
        "fixture",
        DomainRegistration(module_name, "Fixture", supported_version=1),
    )
    data = open_data(tmp_path, DataConfig())
    assert module_name not in sys.modules
    fixture_module = ModuleType(module_name)
    fixture_module.__dict__["Fixture"] = lambda working_dir, backend_name: type(
        "Fixture", (), {"value": (working_dir, backend_name)}
    )()

    monkeypatch.setitem(sys.modules, module_name, fixture_module)
    assert data.fixture.value == (tmp_path, "files")
    assert data.fixture is data.fixture


def test_plans_factory_receives_working_dir_and_backend_without_version_gate(
    tmp_path: Path,
) -> None:
    from varde_data.testing import MemoryPlans

    data = open_data(tmp_path, DataConfig(backends={"plans": "memory"}))
    assert isinstance(data.plans, MemoryPlans)
    assert not (tmp_path / ".cache" / "data" / "plans.version").exists()


def test_messages_domain_opens_files_backend_lazily(tmp_path: Path) -> None:
    from varde_data.backends.files.messages import FilesMessages

    data = open_data(tmp_path, DataConfig(backends={"messages": "files"}))
    assert isinstance(data.messages, FilesMessages)
    assert data.messages is data.messages


def test_addresses_domain_opens_files_backend_without_version_gate(
    tmp_path: Path,
) -> None:
    from varde_data.backends.files.addresses import FilesAddresses

    data = open_data(tmp_path, DataConfig(backends={"addresses": "files"}))
    assert isinstance(data.addresses, FilesAddresses)
    assert data.addresses is data.addresses
    assert not (tmp_path / ".cache" / "data" / "addresses.version").exists()


def test_schema_version_rejects_newer_store(tmp_path: Path) -> None:
    version = tmp_path / "messages.version"
    version.write_text("3\n", encoding="utf-8")
    with pytest.raises(Invalid, match="store schema version 3.*supported version 2"):
        check_schema_version(version, supported=2)


def test_schema_version_is_read_only_when_missing(tmp_path: Path) -> None:
    version = tmp_path / "absent.version"
    check_schema_version(version, supported=1)
    assert not version.exists()
