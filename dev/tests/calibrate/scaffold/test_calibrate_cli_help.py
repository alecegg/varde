from varde_dev.calibrate.cli import COMMANDS, main


def test_help_lists_every_command(capsys):
    assert main(["--help"]) == 0
    output = capsys.readouterr().out

    for command in COMMANDS:
        assert command in output
