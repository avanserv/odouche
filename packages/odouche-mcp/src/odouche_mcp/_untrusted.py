"""What makes text a third party wrote safe to return: no escape sequence, no control character, and a size."""

import re


# As `odouche_cli._output.strip_line_control`, which this package cannot import. The bidirectional
# controls go too: they can reorder what is shown of the text.
_LINE_CONTROL = re.compile(r"[\x00-\x08\x0a-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]")
_CSI = r"(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]"
_STRING = r"[^\x07\x1b\x9c]*"
_END = r"(?:\x07|\x1b\\|\x9c)"
# A 7-bit string that was cut goes to the end of the line. An 8-bit introducer that nothing ends
# is a character of text decoded twice: only it goes, and `bare` is the text after it.
_SEQUENCE = re.compile(
    rf"{_CSI}"
    rf"|\x1b[\]PX^_]{_STRING}{_END}?"  # OSC, DCS, SOS, PM, APC
    rf"|[\x90\x98\x9d\x9e\x9f](?:{_STRING}{_END}|(?P<bare>{_STRING}))"  # the same, in 8 bits
    r"|\x1b[ -/]*[0-~]"  # any other escape
)
_BARE_SEQUENCE = re.compile(_CSI)
# Whatever breaks a line, or would show as a gap in one, the tab included.
_SPACE = re.compile(r"[\t\n\v\f\r\x1c-\x1e\x85\u2028\u2029]+")


def strip_line_control(text: str) -> str:
    """Remove the escape sequences from a line of text that is not ours, then the control characters but the tab.

    The bidirectional controls are among them.
    """
    return _LINE_CONTROL.sub("", _SEQUENCE.sub(_unsequenced, text))


def one_line(text: str, size: int) -> tuple[str, bool]:
    """Return text that is not ours as one line, without escape sequences or control characters, cut to `size` bytes as JSON.

    The second value tells whether it was cut.
    """
    line = strip_line_control(_SPACE.sub(" ", text))
    kept = prefix(line, size)
    return kept, kept != line


def _unsequenced(found: re.Match[str]) -> str:
    """Return what a sequence leaves: nothing, or the text after a bare 8-bit introducer."""
    bare = found["bare"]
    # No string starts in it: each would end where this one does not.
    return _BARE_SEQUENCE.sub("", bare) if bare else ""


def encoded_size(line: str) -> int:
    """Return the bytes a line takes as a JSON string. It has no control character but the tab."""
    return len(line.encode()) + line.count('"') + line.count("\\") + line.count("\t") + 2


def prefix(line: str, size: int) -> str:
    """Return the longest start of a line that takes no more than `size` bytes."""
    kept, over = 0, len(line)
    while kept < over:
        middle = (kept + over + 1) // 2
        if encoded_size(line[:middle]) <= size:
            kept = middle
        else:
            over = middle - 1
    return line[:kept]
