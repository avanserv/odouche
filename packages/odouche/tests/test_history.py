import copy
import json
import logging
from datetime import UTC, datetime

import httpx2
import pytest

from odouche import (
    BuildResult,
    BuildStatus,
    NotFoundError,
    PushedCommit,
    Stage,
    StreamTimeoutError,
    TrackedBuild,
    TrackingKind,
    UpstreamChangedError,
)
from odouche._upstream import history


PATH = "/app/branch/51044/history"
BRANCH = 51044
HASH = "3f2a9c1e5b7d4f608192a3b4c5d6e7f801234567"
MESSAGE = "[FIX] invoicing: round the tax base per line\n\nThe total was rounded once, so lines did not add up."


def trackings(upstream):
    return upstream.bodies[PATH]["result"]["trackings"]


def offsets(upstream):
    return [json.loads(request.content)["params"]["offset"] for request in upstream.requests]


def pages(upstream, total, *, repeat=False, pushed=0):
    """Answer `total` pushes, twenty a page, newest first.

    With `repeat`, every offset answers the first page. With `pushed`, that many events came after
    the first page, so each later one starts that much earlier.
    """
    template = trackings(upstream)[1]

    def answer(request):
        asked = json.loads(request.content)["params"]["offset"]
        offset = 0 if repeat else max(asked - pushed, 0) if asked else 0
        page = [dict(copy.deepcopy(template), id=1000 - at) for at in range(offset, min(offset + 20, total))]

        return httpx2.Response(
            200, json={"jsonrpc": "2.0", "id": 1, "result": {"num_trackings": total, "trackings": page}}
        )

    upstream.bodies[PATH] = answer


def test_yields_each_event_newest_first_with_its_build_and_commits(client, upstream):
    events = list(client.history(BRANCH, timeout=10))

    assert [event.id for event in events] == [930105, 930088, 930051, 930047, 930046]
    assert [event.kind for event in events] == [
        TrackingKind.REBUILD,
        TrackingKind.PUSH,
        TrackingKind.PUSH,
        TrackingKind.PUSH,
        TrackingKind.STAGE,
    ]
    rebuilt, pushed = events[0], events[1]
    assert rebuilt.created_at == datetime(2026, 10, 1, 10, 0, 2, tzinfo=UTC)
    assert rebuilt.build == TrackedBuild(88240, BuildStatus.PROGRESS, "progress", None, None)
    assert pushed.build == TrackedBuild(88212, BuildStatus.DROPPED, "dropped", BuildResult.SUCCESS, "success")
    assert events[3].build is not None
    assert events[3].build.result is BuildResult.FAILED
    assert pushed.commits == (PushedCommit(HASH, MESSAGE, f"https://github.com/Acme-Corp/Odoo-Addons/commit/{HASH}"),)
    assert pushed.pusher == "octo-dev"
    assert (pushed.source_stage, pushed.target_stage) == (None, None)
    assert offsets(upstream) == [0]


def test_the_stage_event_that_created_the_branch_has_no_build_and_no_pusher(client):
    created = list(client.history(BRANCH, timeout=10))[-1]

    assert created.kind is TrackingKind.STAGE
    assert created.build is None
    assert created.commits == ()
    assert created.pusher is None
    assert (created.source_stage, created.target_stage) == (None, Stage.DEVELOPMENT)


def test_a_move_between_stages_has_both_stages(client, upstream):
    trackings(upstream)[-1]["source_stage"] = "dev"
    trackings(upstream)[-1]["target_stage"] = "staging"
    moved = list(client.history(BRANCH, timeout=10))[-1]

    assert (moved.source_stage, moved.target_stage) == (Stage.DEVELOPMENT, Stage.STAGING)


def test_an_unknown_kind_and_status_keep_their_names(client, upstream, caplog):
    trackings(upstream)[1]["tracking_type"] = "merge"
    trackings(upstream)[1]["build"]["status"] = ["frozen", "Frozen"]

    with caplog.at_level(logging.DEBUG, logger="odouche"):
        event = list(client.history(BRANCH, timeout=10))[1]

    assert (event.kind, event.kind_name) == (TrackingKind.UNKNOWN, "merge")
    assert event.build is not None
    assert (event.build.status, event.build.status_name) == (BuildStatus.UNKNOWN, "frozen")
    assert "merge" in caplog.text


def test_nothing_is_asked_before_the_first_event_is_read(client, upstream):
    events = client.history(BRANCH, timeout=10)

    assert upstream.requests == []
    next(events)
    assert offsets(upstream) == [0]


def test_the_next_page_is_asked_once_and_only_when_read_past_the_first(client, upstream):
    pages(upstream, 25)
    events = client.history(BRANCH, limit=100, timeout=10)
    first = [next(events) for _ in range(20)]
    assert offsets(upstream) == [0]
    rest = list(events)

    assert offsets(upstream) == [0, 20]
    assert [event.id for event in first + rest] == list(range(1000, 975, -1))


def test_a_limit_within_the_first_page_asks_only_for_it(client, upstream):
    pages(upstream, 25)

    events = list(client.history(BRANCH, timeout=10))

    assert len(events) == 20
    assert offsets(upstream) == [0]


def test_the_limit_ends_the_events_inside_a_page(client, upstream):
    pages(upstream, 45)

    events = list(client.history(BRANCH, limit=23, timeout=10))

    assert len(events) == 23
    assert offsets(upstream) == [0, 20]


def test_a_page_that_repeats_the_first_raises_the_changed_shape_error(client, upstream):
    pages(upstream, 25, repeat=True)
    events = client.history(BRANCH, limit=100, timeout=10)

    with pytest.raises(UpstreamChangedError) as raised:
        list(events)

    assert raised.value.operation == "history"
    assert raised.value.field == "result.trackings"
    assert offsets(upstream) == [0, 20]


def test_events_read_again_after_a_push_are_skipped(client, upstream):
    pages(upstream, 25, pushed=1)

    events = list(client.history(BRANCH, limit=100, timeout=10))

    assert [event.id for event in events] == list(range(1000, 975, -1))
    assert offsets(upstream) == [0, 20]


def test_an_empty_page_ends_the_events_whatever_the_total(client, upstream):
    upstream.bodies[PATH]["result"]["trackings"] = []

    assert list(client.history(BRANCH, timeout=10)) == []
    assert offsets(upstream) == [0]


def test_an_empty_page_ends_the_events(client, upstream):
    upstream.bodies[PATH]["result"] = {"num_trackings": 0, "trackings": []}

    assert list(client.history(BRANCH, timeout=10)) == []


def test_a_page_still_to_ask_for_at_the_timeout_raises_the_timeout_error(client, upstream, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(history, "_monotonic", lambda: now[0])
    pages(upstream, 25)
    events = client.history(BRANCH, limit=100, timeout=5)

    for _ in range(20):
        next(events)

    now[0] += 5

    with pytest.raises(StreamTimeoutError) as raised:
        next(events)

    assert raised.value.operation == "history"
    assert offsets(upstream) == [0]


@pytest.mark.parametrize(("limit", "timeout"), [(0, 10), (-1, 10), (1, 0), (1, -1)])
def test_a_limit_or_timeout_out_of_range_is_refused_before_any_request(client, upstream, limit, timeout):
    with pytest.raises(ValueError, match=r"at least 1|more than 0"):
        client.history(BRANCH, limit=limit, timeout=timeout)

    assert upstream.requests == []


@pytest.mark.parametrize("branch", ["51044", True, 51044.0])
def test_a_branch_that_is_not_an_integer_is_refused(client, upstream, branch):
    with pytest.raises(TypeError):
        client.history(branch, timeout=10)

    assert upstream.requests == []


def test_a_branch_out_of_reach_is_not_found(client, upstream):
    upstream.failures[PATH] = 404

    with pytest.raises(NotFoundError):
        list(client.history(BRANCH, timeout=10))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", "930088"),
        ("tracking_type", False),
        ("create_date", "30/09/2026"),
        ("build", 88212),
        ("commits", False),
        ("pusher_name", 3),
        ("source_stage", 1),
        ("target_stage", ["dev"]),
    ],
)
def test_names_the_field_of_an_event_that_changed_shape(client, upstream, field, value):
    trackings(upstream)[1][field] = value

    with pytest.raises(UpstreamChangedError) as raised:
        list(client.history(BRANCH, timeout=10))

    assert raised.value.field == f"result.trackings[1].{field}"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", None),
        ("status", "dropped"),
        ("status", ["dropped"]),
        ("status", [1, "Dropped"]),
        ("result", "success"),
        ("result", ["success", None]),
    ],
)
def test_names_the_field_of_a_build_that_changed_shape(client, upstream, field, value):
    trackings(upstream)[1]["build"][field] = value

    with pytest.raises(UpstreamChangedError) as raised:
        list(client.history(BRANCH, timeout=10))

    assert raised.value.field == f"result.trackings[1].build.{field}"


@pytest.mark.parametrize("field", ["identifier", "message", "provider_url"])
def test_names_the_field_of_a_commit_that_changed_shape(client, upstream, field):
    del trackings(upstream)[1]["commits"][0][field]

    with pytest.raises(UpstreamChangedError) as raised:
        list(client.history(BRANCH, timeout=10))

    assert raised.value.field == f"result.trackings[1].commits[0].{field}"


@pytest.mark.parametrize(
    ("body", "field"),
    [({}, "result"), ({"result": []}, "result"), ({"result": {"trackings": []}}, "result.num_trackings")],
)
def test_names_the_part_of_the_answer_that_changed_shape(client, upstream, body, field):
    upstream.bodies[PATH] = body

    with pytest.raises(UpstreamChangedError) as raised:
        list(client.history(BRANCH, timeout=10))

    assert raised.value.field == field
