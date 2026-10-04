from datetime import UTC, datetime, timedelta

import pytest

from odouche_cli import _time
from odouche_cli._time import ago, left


NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_time, "_now", lambda: NOW)


@pytest.mark.parametrize(
    ("delta", "text"),
    [
        (timedelta(seconds=20), "less than a minute"),
        (timedelta(minutes=1), "1 minute"),
        (timedelta(hours=5, minutes=59), "5 hours"),
        (timedelta(days=1, hours=23), "1 day"),
    ],
)
def test_a_duration_is_said_in_its_largest_whole_unit(delta: timedelta, text: str):
    assert ago(NOW - delta) == f"{text} ago"
    assert left(NOW + delta) == f"in {text}"


@pytest.mark.parametrize(
    ("ahead", "text"),
    [
        (timedelta(seconds=20), "less than a minute ago"),
        (timedelta(minutes=1), "in 1 minute"),
        (timedelta(days=3), "in 3 days"),
    ],
)
def test_a_moment_ahead_of_the_clock_is_said_as_ahead_from_a_minute(ahead: timedelta, text: str):
    assert ago(NOW + ahead) == text
