import time

import pytest

from odouche import strip_line_control


BIDI = "\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"


def test_removes_the_bidirectional_controls_and_keeps_the_tab():
    assert strip_line_control("paypal.com" + BIDI + "\tmoc.evil") == "paypal.com\tmoc.evil"


@pytest.mark.parametrize(
    ("line", "stripped"),
    [
        ("\x1b[31mERROR\x1b[0m coloured", "ERROR coloured"),
        ("title \x1b]0;owned\x07 after", "title  after"),
        ("title \x1b]0;owned\x1b\\ after", "title  after"),
        ("c1 \x9b31mred\x9bm \x9d0;t\x9c end", "c1 red  end"),
        ("charset \x1b(B done", "charset  done"),
        ("\tkept\x00\x08\x0b\x0c\r\x7f\x85", "\tkept"),
        ("cut \x1b]0;owned", "cut "),
        ("cut \x1bP1$r", "cut "),
        ("cut \x1b[31", "cut 31"),
        ("cut \x1b", "cut "),
        ("Stra\xc3\x9fe 12 failed: reason", "Stra\xc3e 12 failed: reason"),
        ("bare \x9d one \x9bm\x90 two \x1b[0m end", "bare  one  two  end"),
        ("bare \x9d then \x9d0;t\x9c end", "bare  end"),
    ],
    ids=[
        "CSI",
        "OSC",
        "OSC ended by ST",
        "C1",
        "other escape",
        "control",
        "cut OSC",
        "cut DCS",
        "cut CSI",
        "cut ESC",
        "text decoded twice",
        "bare C1 introducers",
        "bare C1 introducer before an ended one",
    ],
)
def test_removes_whole_sequences_and_control_characters_but_the_tab(line: str, stripped: str):
    assert strip_line_control(line) == stripped


@pytest.mark.parametrize(
    "line",
    [
        "\x1b]" * 32768,
        "\x9d" * 65536,
        "\x1b[" * 32768,
        "\x1bP" * 32768,
        "\x9d" * 60000 + "\x1b[",
        "\x9d\x9b" * 32768,
    ],
    ids=["OSC", "C1 OSC", "CSI", "DCS", "C1 OSC before a cut CSI", "C1 OSC and CSI"],
)
def test_a_long_line_of_sequences_that_never_end_is_stripped_quickly(line: str):
    started = time.perf_counter()

    assert strip_line_control(line) == ""
    assert time.perf_counter() - started < 5
