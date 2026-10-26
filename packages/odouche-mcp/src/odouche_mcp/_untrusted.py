"""What makes text a third party wrote safe to return: no escape sequence, no control character, and a size."""

import re

import odouche


# Whatever breaks a line, or would show as a gap in one, the tab included.
_SPACE = re.compile(r"[\t\n\v\f\r\x1c-\x1e\x85\u2028\u2029]+")


def one_line(text: str, size: int) -> tuple[str, bool]:
    """Return text that is not ours as one line, without escape sequences or control characters, cut to `size` bytes as JSON.

    The second value tells whether it was cut.
    """
    line = odouche.strip_line_control(_SPACE.sub(" ", text))
    kept = prefix(line, size)
    return kept, kept != line


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
