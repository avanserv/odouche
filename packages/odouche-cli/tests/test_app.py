import pytest
from typer.testing import CliRunner

import odouche
import odouche_cli
from odouche_cli import app as app_module
from odouche_cli.app import app, main


runner = CliRunner()


def test_version_reports_the_cli_and_the_library():
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == f"osh {odouche_cli.__version__} (odouche {odouche.__version__})"


def test_no_arguments_shows_help():
    result = runner.invoke(app, [])

    assert "Usage:" in result.output
    assert "--version" in result.output


def test_main_runs_the_application(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []
    monkeypatch.setattr(app_module, "app", lambda: calls.append("run"))

    main()

    assert calls == ["run"]
