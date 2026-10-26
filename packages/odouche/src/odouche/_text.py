"""Text that a third party wrote, made safe to show."""

import re


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


def strip_line_control(text: str) -> str:
    """Remove the escape sequences from a line of text that is not ours, then the control characters but the tab.

    The control characters are C0, DEL, C1 and the bidirectional ones, which can reorder what is
    shown. A log line, a mail or an audit entry is written by a build's code or another user: this
    is what a frontend applies before it shows one.
    """
    return _LINE_CONTROL.sub("", _SEQUENCE.sub(_unsequenced, text))


def _unsequenced(found: re.Match[str]) -> str:
    """Return what a sequence leaves: nothing, or the text after a bare 8-bit introducer."""
    bare = found["bare"]
    # No string starts in it: each would end where this one does not.
    return _BARE_SEQUENCE.sub("", bare) if bare else ""
