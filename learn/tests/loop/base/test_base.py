import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from varde_data.errors import Invalid
from varde_data.paths import resolve_learn_store
from varde_learn.loop.errors import (
    NotImplemented,
    StoreConfig,
    StoreIo,
    StoreSchemaTooNew,
)
from varde_learn.loop.redact import Redacted, apply
from varde_learn.loop.store.paths import resolve_store_dir


def test_learn_errors_expose_stable_codes_and_messages() -> None:
    assert NotImplemented("friction").code == "not_implemented"
    assert str(NotImplemented("friction")) == "not implemented: friction"
    assert StoreConfig(Path("config.toml"), "bad TOML").code == "store_config_error"
    assert str(StoreSchemaTooNew(5, 4)) == (
        "friction store schema version 5 is newer than supported version 4; "
        "upgrade varde-learn"
    )


def test_resolve_learn_store_uses_environment_before_config(
    monkeypatch, tmp_path: Path
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "config.toml").write_text(' [default]\nlearn = "from-config"\n')
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))
    monkeypatch.setenv("VARDE_LEARN_STORE", "from-env")
    assert resolve_learn_store() == Path.cwd() / "from-env"


def test_resolve_learn_store_reads_config_and_falls_back(
    monkeypatch, tmp_path: Path
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))
    (config / "config.toml").write_text('[default]\nlearn = "from-config"\n')
    assert resolve_learn_store() == Path.cwd() / "from-config"
    (config / "config.toml").unlink()
    assert resolve_learn_store() == config / "learn"


def test_resolve_learn_store_rejects_invalid_config(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path))
    config = tmp_path / "config.toml"
    config.write_text('[default]\nlearn = "  "\n')
    with pytest.raises(Invalid, match="non-empty path string"):
        resolve_learn_store()


def test_resolve_store_dir_maps_data_config_and_io_errors(
    monkeypatch, tmp_path: Path
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    config_path = config / "config.toml"
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))
    monkeypatch.delenv("VARDE_LEARN_STORE", raising=False)
    config_path.write_text('[default]\nlearn = "  "\n')
    with pytest.raises(StoreConfig) as config_error:
        resolve_store_dir()
    assert config_error.value.code == "store_config_error"
    assert str(config_error.value) == (
        f"invalid global learn store configuration at {config_path}: "
        "`default.learn` must be a non-empty path string"
    )

    loop = tmp_path / "loop"
    loop.symlink_to(loop)
    monkeypatch.setenv("VARDE_LEARN_STORE", str(loop))
    with pytest.raises(StoreIo) as io_error:
        resolve_store_dir()
    assert io_error.value.code == "store_io_error"
    assert io_error.value.operation == "resolve symlinked store path"


def test_redaction_adapter_counts_notices(monkeypatch) -> None:
    class StubRedactor:
        def __init__(self, config):
            assert config is not None

        def redact(self, text):
            return SimpleNamespace(
                text=text.replace("secret", "[redacted]"),
                notices=[SimpleNamespace(count=2)],
            )

    redactor_module = ModuleType("varde_core.redact")
    redactor_module.__dict__.update({"RedactConfig": object, "Redactor": StubRedactor})
    monkeypatch.setitem(sys.modules, "varde_core.redact", redactor_module)
    assert apply("secret").text == "[redacted]"
    assert apply("secret").count == 2
    assert Redacted("plain", 0) == Redacted("plain", 0)
