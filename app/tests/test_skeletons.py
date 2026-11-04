import importlib.metadata


def test_entry_points_load_and_expose_module_operations() -> None:
    entries = importlib.metadata.entry_points(group="varde.modules")
    assert entries
    for entry in entries:
        module = entry.load()()
        assert module.name == entry.name
        assert callable(module.run)
        assert callable(module.help)
