from varde_runner import main


def test_service_print_launchd(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["varde-runner", "service", "print", "launchd"])
    main()
    assert "RunAtLoad" in capsys.readouterr().out


def test_service_print_systemd(monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.argv", ["varde-runner", "service", "print", "systemd-user"]
    )
    main()
    assert "WantedBy=default.target" in capsys.readouterr().out
