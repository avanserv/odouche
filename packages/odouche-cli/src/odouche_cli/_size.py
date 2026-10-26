"""A count of bytes as a size, for a table."""

_UNITS = ("B", "KiB", "MiB", "GiB")
_STEP = 1024


def size(count: int) -> str:
    """Say a count of bytes in its largest unit up to GiB, to a tenth."""
    value = float(count)

    for unit in _UNITS[:-1]:
        # Compared as shown, so 1048575 bytes is 1.0 MiB and not 1024.0 KiB.
        if round(value, 1) < _STEP:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"

        value /= _STEP

    return f"{value:.1f} {_UNITS[-1]}"
