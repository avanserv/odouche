import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from enum import StrEnum

import pytest
import typer
from typer.testing import CliRunner

import odouche
from odouche_cli import _output
from odouche_cli._output import Column, Format, Output, to_json
from odouche_cli.app import app, root


SENTINEL = "sentinel-session-value"
ANSI = re.compile(r"\x1b\[")
BOX = re.compile(r"[─-╿]")


class Colour(StrEnum):
    RED = "red"


@dataclass(frozen=True, slots=True)
class Owner:
    name: str


@dataclass(frozen=True, slots=True)
class Thing:
    id: int
    colour: Colour
    made_at: datetime
    owner: Owner
    note: str | None = None


THING = Thing(1, Colour.RED, datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone(timedelta(hours=2))), Owner("ann"))
OTHER = Thing(2, Colour.RED, datetime(2026, 1, 3, tzinfo=UTC), Owner("bob"), note="x" * 200)
THING_JSON = {
    "id": 1,
    "colour": "red",
    "made_at": "2026-01-02T03:04:05+02:00",
    "owner": {"name": "ann"},
    "note": None,
}

COLUMNS = [
    Column[Thing]("ID", lambda thing: thing.id),
    Column[Thing]("Owner", lambda thing: thing.owner.name),
    Column[Thing]("Note", lambda thing: thing.note),
]

runner = CliRunner()


@pytest.fixture
def terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(_output, "_is_terminal", lambda: True)


def test_json_rows_are_the_models_and_nothing_else(capsys: pytest.CaptureFixture[str]):
    Output(Format.JSON).rows([THING], COLUMNS, empty="No things.")

    captured = capsys.readouterr()
    assert json.loads(captured.out) == [THING_JSON]
    assert captured.err == ""


def test_one_model_has_the_same_json_shape_as_a_row(capsys: pytest.CaptureFixture[str]):
    Output(Format.JSON).one(THING, COLUMNS)

    assert json.loads(capsys.readouterr().out) == THING_JSON


def test_a_piped_table_is_plain_and_unwrapped(capsys: pytest.CaptureFixture[str]):
    Output().rows([THING, OTHER], COLUMNS, empty="No things.")

    lines = capsys.readouterr().out.splitlines()
    assert [line.split() for line in lines] == [["ID", "Owner", "Note"], ["1", "ann"], ["2", "bob", "x" * 200]]
    assert all(line == line.rstrip() for line in lines)


@pytest.mark.parametrize("variable", ["GITHUB_ACTIONS", "FORCE_COLOR"])
def test_a_piped_table_stays_plain_where_colour_is_forced(
    variable: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setenv(variable, "true")
    output = Output()

    output.rows([THING], COLUMNS, empty="No things.")
    output.one(THING, COLUMNS)

    out = capsys.readouterr().out
    assert not ANSI.search(out)
    assert not BOX.search(out)


@pytest.mark.usefixtures("terminal")
def test_a_terminal_table_has_a_rule_under_its_header(capsys: pytest.CaptureFixture[str]):
    Output().rows([THING], COLUMNS, empty="No things.")

    assert BOX.search(capsys.readouterr().out)


@pytest.mark.usefixtures("terminal")
def test_no_color_makes_a_terminal_table_plain(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    monkeypatch.setenv("NO_COLOR", "1")

    Output().rows([THING], COLUMNS, empty="No things.")

    out = capsys.readouterr().out
    assert not ANSI.search(out)
    assert not BOX.search(out)


def test_one_model_as_a_table_pairs_headers_with_values(capsys: pytest.CaptureFixture[str]):
    Output().one(THING, COLUMNS)

    lines = capsys.readouterr().out.splitlines()
    assert [line.split() for line in lines] == [["ID", "1"], ["Owner", "ann"], ["Note"]]


def test_a_cell_is_not_read_as_markup(capsys: pytest.CaptureFixture[str]):
    Output().rows([Owner("[bold]ann[/bold] :smile:")], [Column[Owner]("Name", lambda owner: owner.name)], empty="")

    assert "[bold]ann[/bold] :smile:" in capsys.readouterr().out


def test_an_empty_result_is_an_empty_json_list(capsys: pytest.CaptureFixture[str]):
    Output(Format.JSON).rows([], COLUMNS, empty="No things.")

    captured = capsys.readouterr()
    assert json.loads(captured.out) == []
    assert captured.err == ""


def test_an_empty_table_is_one_line_on_stderr(capsys: pytest.CaptureFixture[str]):
    Output().rows([], COLUMNS, empty="No things.")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "No things.\n"


def test_a_json_stream_prints_each_row_as_it_arrives(capsys: pytest.CaptureFixture[str]):
    seen: list[str] = []

    def things() -> Iterator[Thing]:
        yield THING
        seen.append(capsys.readouterr().out)
        yield OTHER

    Output(Format.JSON).stream(things(), lambda thing: thing.owner.name)

    assert [json.loads(line) for line in seen[0].splitlines()] == [THING_JSON]
    assert json.loads(capsys.readouterr().out)["id"] == OTHER.id


def test_a_table_stream_prints_the_line_of_each_row(capsys: pytest.CaptureFixture[str]):
    Output().stream(iter([THING, OTHER]), lambda thing: thing.owner.name)

    assert capsys.readouterr().out == "ann\nbob\n"


def test_a_datetime_without_an_offset_is_refused():
    with pytest.raises(ValueError, match="offset"):
        to_json(datetime(2026, 1, 2))  # noqa: DTZ001 - the naive datetime is the case


def test_an_unknown_type_is_refused_without_its_value():
    with pytest.raises(TypeError, match="Secret") as raised:
        to_json([odouche.Secret(SENTINEL)])

    assert SENTINEL not in str(raised.value)


def run(*args: str):
    """Run a stub command under the real root callback."""
    stub = typer.Typer()
    stub.callback()(root)

    @stub.command()
    def show(ctx: typer.Context) -> None:  # pyright: ignore[reportUnusedFunction]
        ctx.obj.rows([THING], COLUMNS, empty="No things.")

    return runner.invoke(stub, [*args, "show"])


def test_the_format_option_selects_json():
    result = run("--format", "json")

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [THING_JSON]


def test_the_format_defaults_to_a_table():
    assert run().stdout.split()[:3] == ["ID", "Owner", "Note"]


def test_an_unknown_format_is_a_usage_error():
    result = runner.invoke(app, ["--format", "yaml", "--version"])

    assert result.exit_code == 2
