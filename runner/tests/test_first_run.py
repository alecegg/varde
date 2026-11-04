from varde_runner.first_run import checklist


def test_checklist_reports_each_setup_step_independently() -> None:
    status = {
        "data_root": "workspace-root",
        "service": {"installed": False, "managed": False},
        "harnesses": [{"enabled": True, "login": "ready"}],
        "default_roles_enabled": False,
    }

    steps = checklist(status)

    assert [step["id"] for step in steps] == [
        "data_root",
        "service",
        "harness",
        "roles",
    ]
    assert [step["done"] for step in steps] == [True, False, True, False]
    assert all(step["hint"] and step["link"] for step in steps)


def test_checklist_accepts_managed_service_and_enabled_default_roles() -> None:
    steps = checklist(
        {
            "data_root": "workspace-root",
            "service": {"installed": False, "managed": True},
            "harnesses": [{"enabled": True, "login": "ready"}],
            "default_roles_enabled": True,
        }
    )

    assert all(step["done"] for step in steps)
