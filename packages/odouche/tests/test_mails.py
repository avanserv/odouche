import dataclasses
import json
import time
from datetime import UTC, datetime
from email.message import EmailMessage

import httpx2
import pytest

from odouche import (
    Mail,
    MailAttachment,
    MailContent,
    NotFoundError,
    OdoucheError,
    Stage,
    UpstreamChangedError,
    _mime,
)
from odouche._upstream import mails


PROJECT = "acme-shop"
BRANCH = 51044
BUILD = 88212
WORKER = "eupd00.odoo.com"
TOKEN = "t0k3n-0f-th3-pr0j3ct"
BUILDS = "/app/branch/51044/builds"
INFO = "/app/project/acme-shop/get_info"
FETCH = "/paas/88212/mail/json/fetch"
MESSAGE = "/paas/88212/mail/json/message"
FIRST = "1761213600.M1P1Q1.build"
# The most CPU time a parse of a large mail takes, on a shared runner under coverage: CPU time, since
# a stalled runner lengthens the wall clock and not it. Each mail timed against it takes under a
# second here under coverage, and more than a minute for the code it guards against.
BUDGET = 15


class Messages:
    """Answers the `message` request as a worker does, by the id it is sent, and keeps the ids."""

    def __init__(self, answer):
        self.answer = answer
        self.asked = []
        # The source of each id, in place of the fixture's.
        self.sources = {}

    def __call__(self, request):
        params = json.loads(request.content)["params"]
        self.asked.append(params["message_id"])
        answer = json.loads(json.dumps(self.answer))

        if params["message_id"] in self.sources:
            answer["result"]["source"] = self.sources[params["message_id"]]

        return httpx2.Response(200, json=answer)


@pytest.fixture
def messages(upstream):
    upstream.bodies[INFO]["result"]["access_token"] = TOKEN
    upstream.bodies[MESSAGE] = Messages(upstream.load("mail_message.json"))

    return upstream.bodies[MESSAGE]


@pytest.fixture
def branch(client):
    return next(branch for branch in client.branches(PROJECT) if branch.id == BRANCH)


@pytest.fixture
def build(client):
    return client.build(BRANCH, BUILD)


@pytest.fixture
def worker_requests(upstream, branch, build, messages):
    """The requests sent after the branch and the build were read."""
    upstream.requests.clear()

    return upstream.requests


def source(content, subtype="plain", **headers):
    message = EmailMessage()
    message["From"] = "Acme <noreply@example.com>"

    for name, value in headers.items():
        message[name] = value

    message.set_content(content, subtype=subtype)

    return message.as_string()


def test_lists_the_mails_newest_first_with_their_headers(client, branch, build, worker_requests):
    listed = client.mails(PROJECT, branch, build)

    # The second is dated in another zone.
    assert [mail.id for mail in listed] == ["1761217200.M2P1Q2.build", FIRST, "1761206400.M3P1Q3.build"]
    assert listed[1] == Mail(
        id=FIRST,
        date=datetime(2026, 10, 23, 10, tzinfo=UTC),
        date_text="Thu, 23 Oct 2026 10:00:00 +0000",
        sender="Acme <noreply@example.com>",
        recipients="Jane Doe <jane@example.com>, billing@example.com",
        subject="Your invoice INV/2026/0042",
    )
    assert listed[0].date == datetime(2026, 10, 23, 11, tzinfo=UTC)
    assert [(request.url.host, request.url.path) for request in worker_requests] == [
        ("www.odoo.sh", BUILDS),
        ("www.odoo.sh", INFO),
        (WORKER, FETCH),
    ]


def test_a_build_that_caught_nothing_lists_nothing(client, upstream, branch, build, messages):
    # The one answer seen.
    upstream.bodies[FETCH] = {"jsonrpc": "2.0", "id": 50, "result": []}

    assert client.mails(PROJECT, branch, build) == []


def test_lists_at_most_the_limit(client, branch, build, messages):
    assert [mail.id for mail in client.mails(PROJECT, branch, build, limit=1)] == ["1761217200.M2P1Q2.build"]


@pytest.mark.parametrize("limit", [0, -1])
def test_a_limit_under_one_is_refused(client, branch, build, limit):
    with pytest.raises(ValueError, match="at least 1"):
        client.mails(PROJECT, branch, build, limit=limit)


def test_a_date_that_is_not_one_is_kept_as_text_and_listed_last(client, upstream, branch, build, messages):
    upstream.bodies[FETCH]["result"][0]["date"] = "yesterday"
    listed = client.mails(PROJECT, branch, build)

    assert (listed[-1].id, listed[-1].date, listed[-1].date_text) == (FIRST, None, "yesterday")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-10-23 10:00:00", datetime(2026, 10, 23, 10, tzinfo=UTC)),
        ("Thu, 23 Oct 2026 10:00:00 -0000", datetime(2026, 10, 23, 10, tzinfo=UTC)),
        ("Fri, 31 Dec 9999 23:30:00 -0100", None),
        ("", None),
    ],
)
def test_a_date_is_read_as_a_mail_or_odoo_sh_writes_it(text, expected):
    assert mails._when(text) == expected


def test_a_missing_header_is_empty(client, upstream, branch, build, messages):
    upstream.bodies[FETCH]["result"][0].update({"subject": False, "to": None})

    listed = next(mail for mail in client.mails(PROJECT, branch, build) if mail.id == FIRST)

    assert (listed.subject, listed.recipients) == ("", "")


@pytest.mark.parametrize(("field", "value"), [("id", True), ("id", ""), ("id", None), ("from", 3), ("date", [])])
def test_a_field_of_another_type_is_a_changed_upstream(client, upstream, branch, build, messages, field, value):
    upstream.bodies[FETCH]["result"][0][field] = value

    with pytest.raises(UpstreamChangedError) as raised:
        client.mails(PROJECT, branch, build)

    assert raised.value.field == f"result[0].{field}"


def test_half_a_surrogate_pair_in_a_header_or_an_id_does_not_break_the_listing(
    client, upstream, branch, build, messages
):
    answer = upstream.bodies[FETCH]
    answer["result"][0].update({"id": "m\ud800", "subject": "Hi \udc80there"})
    # As JSON escapes them: the half of a pair cannot be written as UTF-8.
    upstream.bodies[FETCH] = lambda _: httpx2.Response(200, content=json.dumps(answer).encode())
    listed = next(mail for mail in client.mails(PROJECT, branch, build) if mail.id == "m?")

    assert listed.subject == "Hi ?there"

    with pytest.raises(NotFoundError, match="cannot be sent back"):
        client.mail(PROJECT, branch, build, "m?")

    assert messages.asked == []


def test_a_list_over_the_cap_is_an_error_that_names_it(client, upstream, branch, build, messages, monkeypatch):
    monkeypatch.setattr(mails, "MAX_MESSAGE", 1048576)
    upstream.bodies[FETCH]["result"] = [
        upstream.bodies[FETCH]["result"][0] | {"id": str(number), "subject": "x" * 1024} for number in range(1100)
    ]

    for call in (lambda: client.mails(PROJECT, branch, build), lambda: client.mail(PROJECT, branch, build, "1")):
        with pytest.raises(OdoucheError, match="over 1 MiB as the worker lists them"):
            call()

    assert messages.asked == []


def test_a_build_that_waits_for_a_worker_has_no_mail(client, upstream, branch, messages):
    waiting = client.build(BRANCH, 88240)
    upstream.requests.clear()

    assert client.mails(PROJECT, branch, waiting) == []

    with pytest.raises(NotFoundError, match="waits for a worker"):
        client.mail(PROJECT, branch, waiting, FIRST)

    assert {request.url.host for request in upstream.requests} == {"www.odoo.sh"}


@pytest.mark.parametrize("stage", [Stage.PRODUCTION, Stage.UNKNOWN])
def test_a_branch_of_another_stage_is_refused_before_any_request(client, branch, build, worker_requests, stage):
    staged = dataclasses.replace(branch, stage=stage, stage_name="production")

    with pytest.raises(NotFoundError, match="Branch feature-invoicing is production"):
        client.mails(PROJECT, staged, build)

    with pytest.raises(NotFoundError, match="development or a staging build only"):
        client.mail(PROJECT, staged, build, FIRST)

    assert worker_requests == []


def test_a_staging_branch_has_its_mails(client, branch, build, messages):
    staged = dataclasses.replace(branch, stage=Stage.STAGING, stage_name="staging")

    assert len(client.mails(PROJECT, staged, build)) == 3


def test_a_build_of_another_branch_is_a_value_error(client, branch, build, worker_requests):
    other = dataclasses.replace(branch, id=51020)

    with pytest.raises(ValueError, match="not of branch"):
        client.mails(PROJECT, other, build)

    with pytest.raises(ValueError, match="not of branch"):
        client.mail(PROJECT, other, build, FIRST)

    assert worker_requests == []


def test_a_build_that_is_no_longer_listed_is_not_found(client, branch, build, messages):
    with pytest.raises(NotFoundError):
        client.mails(PROJECT, branch, dataclasses.replace(build, id=1))


def test_the_worker_gets_the_token_and_never_the_session(client, branch, build, worker_requests, session):
    client.mail(PROJECT, branch, build, FIRST)

    fetch, message = (request for request in worker_requests if request.url.host == WORKER)
    assert json.loads(fetch.content)["params"] == {"token": TOKEN}
    assert json.loads(message.content)["params"] == {"message_id": FIRST, "token": TOKEN}

    for request in (fetch, message):
        assert request.method == "POST"
        assert "Cookie" not in request.headers
        assert TOKEN not in str(request.url)
        assert session.encode() not in request.content


def test_reads_one_mail_with_its_text_and_its_attachments(client, branch, build, messages):
    content = client.mail(PROJECT, branch, build, FIRST)

    assert content == MailContent(
        mail=client.mails(PROJECT, branch, build)[1],
        cc="accounting@example.com",
        body="Dear Jane,\n\nHere is your invoice INV/2026/0042 for 1 250,00 \u20ac.\n\nAcme",
        attachments=(MailAttachment(name="invoice.pdf", size=26),),
        truncated=False,
    )


@pytest.mark.parametrize("listed_id", [7, "7"])
def test_the_id_is_sent_back_as_the_worker_typed_it(client, upstream, branch, build, messages, listed_id):
    upstream.bodies[FETCH]["result"][0]["id"] = listed_id

    assert client.mail(PROJECT, branch, build, "7").mail.id == "7"
    assert messages.asked == [listed_id]


def test_a_mail_the_build_did_not_catch_is_not_found_and_not_asked_for(client, branch, build, messages):
    with pytest.raises(NotFoundError, match=r"caught no mail '\.\./x'"):
        client.mail(PROJECT, branch, build, "../x")

    assert messages.asked == []


def test_an_html_body_is_read_as_text_and_nothing_in_it_is_followed(client, branch, build, messages):
    html = (
        "<html><head><title>Hidden</title><style>p { color: red }</style></head><body>"
        "<script>alert('x')</script><p>Hello&nbsp;Jane &amp; co,</p><p>Line one<br>line   two</p>"
        '<img src="https://tracker.example.com/pixel.png">'
        '<p><a href="https://shop.example.com/reset?t=1">Reset it</a> or <a href="mailto:a@example.com">write</a></p>'
        '<div><a href="https://shop.example.com">https://shop.example.com</a></div></body></html>'
    )
    messages.sources[FIRST] = source(html, subtype="html")
    body = client.mail(PROJECT, branch, build, FIRST).body

    assert body == (
        "Hello Jane & co,\n\nLine one\nline two\n\nReset it <https://shop.example.com/reset?t=1> or write\n\n"
        "https://shop.example.com"
    )


def test_a_head_nothing_closes_ends_at_the_body(client, branch, build, messages):
    messages.sources[FIRST] = source("<head><title>t</title><body>Kept", subtype="html")

    assert client.mail(PROJECT, branch, build, FIRST).body == "Kept"


def test_a_plain_only_mail_is_read_unchanged(client, branch, build, messages):
    messages.sources[FIRST] = source("\x1b]0;title\x07Plain\n", Cc="")
    content = client.mail(PROJECT, branch, build, FIRST)

    assert (content.body, content.cc, content.attachments) == ("\x1b]0;title\x07Plain\n", "", ())


def test_a_body_in_a_charset_python_does_not_know_is_read_as_utf_8(client, branch, build, messages):
    messages.sources[FIRST] = (
        "From: a@example.com\nContent-Type: text/plain; charset=x-unknown\nContent-Transfer-Encoding: 8bit\n\n\u00e9t\u00e9\n"
    )

    assert client.mail(PROJECT, branch, build, FIRST).body == "\u00e9t\u00e9\n"


def test_a_long_html_body_is_cut_before_it_is_read(client, branch, build, messages, monkeypatch):
    monkeypatch.setattr(_mime, "_MAX_HTML", 20)
    messages.sources[FIRST] = source("<p>" + "x" * 50 + "</p>", subtype="html")
    content = client.mail(PROJECT, branch, build, FIRST)

    assert (content.body, content.truncated) == ("x" * 17, True)


def test_a_body_is_cut_at_a_byte_count_and_never_inside_a_character(client, branch, build, messages, monkeypatch):
    monkeypatch.setattr(_mime, "MAX_BODY", 5)
    messages.sources[FIRST] = source("\u00e9\u00e9\u00e9\u00e9")
    content = client.mail(PROJECT, branch, build, FIRST)

    assert (content.body, content.truncated) == ("\u00e9\u00e9", True)


def seconds(text):
    """Return the CPU time of the fastest of three parses: a noisy neighbour on a shared runner slows one, not all."""
    runs = []

    for _ in range(3):
        started = time.process_time()
        _mime.parse(text)
        runs.append(time.process_time() - started)

    return min(runs)


def headers_and_parts(size):
    headers = "".join(f"X-Header-{number}: v\n" for number in range(size))
    parts = "".join(f"--x\nContent-Type: text/plain\n\nx{number}\n" for number in range(size))

    return f"From: a@example.com\n{headers}Content-Type: multipart/mixed; boundary=x\n\n{parts}--x--\n"


def test_headers_written_to_be_slow_to_parse_are_read_quickly():
    # The default policy of `email` takes this mail more than a minute and a half: its `Cc` and its
    # parameters are parsed in a time that grows faster than their size. Up to Python 3.12.12, so
    # are the parameters with `compat32`, read again for each part and for the attachment's name.
    cc = ", ".join(f"user{number} <user{number}@example.com>" for number in range(64000))
    parameters = "; ".join(f"p{number}=v{number}" for number in range(160000))
    text = (
        f"From: a@example.com\nCc: {cc}\nContent-Type: multipart/mixed; boundary=x; {parameters}\n\n--x\n"
        "Content-Type: text/plain\n\nHello\n--x\nContent-Type: application/pdf\n"
        f"Content-Disposition: attachment; filename=a.pdf; {parameters}\nContent-Transfer-Encoding: base64\n\n"
        "AAAA\n--x--\n"
    )

    started = time.process_time()
    parsed = _mime.parse(text)

    assert time.process_time() - started < BUDGET
    assert (parsed.body, parsed.attachments) == ("Hello", (MailAttachment("a.pdf", 3),))
    assert parsed.cc.startswith("user0 <user0@example.com>, user1")


def test_the_parameters_of_a_header_are_read_from_its_start_only():
    parameters = "; ".join(f"p{number}=v{number}" for number in range(10000))
    parsed = _mime.parse(
        "From: a@example.com\nContent-Type: multipart/mixed; boundary=x\n\n--x\n"
        f"Content-Disposition: attachment; {parameters}; filename=a.pdf\n\nx\n--x--\n"
    )

    assert (parsed.attachments, parsed.truncated) == ((MailAttachment("", 1),), True)


def test_a_mail_of_many_headers_and_many_parts_is_read_in_a_time_in_line_with_its_size():
    # The parser asks the mail's type for each of its parts, which walks every header of the mail.
    # Eight times the headers and the parts take this code about 8 times as long, and that walk
    # about 50: a ratio holds on a slow runner under coverage, where a time would not.
    small = headers_and_parts(2000)
    parsed = _mime.parse(small)

    assert (parsed.body, parsed.truncated) == ("x0", True)
    assert seconds(headers_and_parts(16000)) < 20 * seconds(small)


def test_a_header_of_encoded_words_is_decoded_from_its_start_only():
    # Decoding all of it takes this mail more than a minute: its first 65536 characters, a few milliseconds.
    cc = "=?utf-8?b?SsOpcsO0bWU=?= " * 200000
    started = time.process_time()
    parsed = _mime.parse(f"From: a@example.com\nCc: {cc}\n\nHello\n")

    assert time.process_time() - started < BUDGET
    assert parsed.cc.startswith("J\u00e9r\u00f4me")
    assert len(parsed.cc) < len(cc)
    assert (parsed.body, parsed.truncated) == ("Hello\n", True)


def test_the_parts_are_read_up_to_a_cap():
    parts = "".join(f"--x\nContent-Disposition: attachment; filename=f{number}\n\nx\n" for number in range(5000))
    started = time.process_time()
    parsed = _mime.parse(f"From: a@example.com\nContent-Type: multipart/mixed; boundary=x\n\n{parts}--x--\n")

    assert time.process_time() - started < BUDGET
    assert 0 < len(parsed.attachments) < 1000
    assert parsed.attachments[0] == MailAttachment("f0", 1)
    assert parsed.truncated


def test_a_forwarded_mail_is_an_attachment_and_its_text_not_the_body(client, branch, build, messages):
    messages.sources[FIRST] = (
        "From: a@example.com\nContent-Type: multipart/mixed; boundary=x\n\n--x\nContent-Type: text/html\n\n"
        "<p>Outer</p>\n--x\nContent-Type: message/rfc822\n\nFrom: b@example.com\nSubject: Fwd\n\nInner\n--x--\n"
    )

    content = client.mail(PROJECT, branch, build, FIRST)

    assert content.body == "Outer"
    assert content.attachments == (MailAttachment("", 0),)


def test_text_that_is_not_ascii_in_an_encoded_part_is_decoded(client, branch, build, messages):
    messages.sources[FIRST] = (
        "From: a@example.com\nContent-Type: text/plain; charset=utf-8\nContent-Transfer-Encoding: quoted-printable\n\n"
        "prix 5\u20ac =C3=A9\n"
    )

    assert client.mail(PROJECT, branch, build, FIRST).body == "prix 5\u20ac \u00e9\n"


def test_half_a_surrogate_pair_in_the_source_leaves_the_rest_readable():
    parsed = _mime.parse("From: a@example.com\nCc: a\ud800b\n\nHello\n")

    assert (parsed.cc, parsed.body, parsed.truncated) == ("a?b", "Hello\n", False)


def test_a_charset_that_is_not_a_name_is_read_as_utf_8():
    parsed = _mime.parse('From: a@example.com\nContent-Type: text/plain; charset="utf-8\x00"\n\n\u00e9t\u00e9\n')

    assert (parsed.body, parsed.truncated) == ("\u00e9t\u00e9\n", False)


def test_an_encoded_word_is_decoded_and_one_in_an_unknown_charset_kept(client, branch, build, messages):
    messages.sources[FIRST] = (
        "From: a@example.com\nCc: =?utf-8?q?Jos=C3=A9?= <j@example.com>\nContent-Type: multipart/mixed; boundary=x\n\n"
        '--x\nContent-Type: text/plain\n\nHi\n--x\nContent-Disposition: attachment; filename="=?x-bogus?q?a?="\n\n'
        "data\n--x--\n"
    )

    content = client.mail(PROJECT, branch, build, FIRST)

    assert content.cc == "Jos\u00e9 <j@example.com>"
    assert content.attachments == (MailAttachment("=?x-bogus?q?a?=", 4),)


def test_a_long_body_is_cut_and_says_so(client, branch, build, messages, monkeypatch):
    monkeypatch.setattr(_mime, "MAX_BODY", 10)
    messages.sources[FIRST] = source("x" * 50)
    content = client.mail(PROJECT, branch, build, FIRST)

    assert (content.body, content.truncated) == ("x" * 10, True)


def test_a_mail_over_the_cap_is_not_read(client, branch, build, messages, monkeypatch):
    monkeypatch.setattr(mails, "MAX_MESSAGE", 1000)
    messages.sources[FIRST] = source("x" * 2000)
    content = client.mail(PROJECT, branch, build, FIRST)

    assert content == MailContent(mail=content.mail, cc="", body="", attachments=(), truncated=True)
    assert content.mail.id == FIRST


def test_a_source_that_cannot_be_read_raises_nothing(client, branch, build, messages, monkeypatch):
    def broken(*_):
        raise IndexError("broken")

    monkeypatch.setattr("email.message_from_bytes", broken)

    content = client.mail(PROJECT, branch, build, FIRST)

    assert (content.body, content.attachments, content.truncated) == ("", (), True)


@pytest.mark.parametrize(
    "text",
    [
        "no headers at all",
        "Content-Type: multipart/mixed\n\n--x\n",
        "From: \x00\nSubject: =?bogus?q?x?=\nContent-Type: text/plain; charset=\n\nx",
        "",
    ],
)
def test_a_malformed_source_raises_nothing(client, branch, build, messages, text):
    messages.sources[FIRST] = text

    assert isinstance(client.mail(PROJECT, branch, build, FIRST), MailContent)


def test_a_message_answer_without_a_source_is_a_changed_upstream(client, branch, build, messages):
    del messages.answer["result"]["source"]

    with pytest.raises(UpstreamChangedError) as raised:
        client.mail(PROJECT, branch, build, FIRST)

    assert raised.value.field == "result.source"


def test_the_token_of_the_body_url_is_in_nothing_returned(client, branch, build, messages):
    content = client.mail(PROJECT, branch, build, FIRST)

    assert "/mail/body" not in repr(content)
    assert "token=" not in repr(content)
    assert TOKEN not in repr(content)


def test_mails_are_immutable(client, branch, build, messages):
    content = client.mail(PROJECT, branch, build, FIRST)

    with pytest.raises(dataclasses.FrozenInstanceError):
        content.body = "other"

    with pytest.raises(dataclasses.FrozenInstanceError):
        content.mail.subject = "other"

    with pytest.raises(dataclasses.FrozenInstanceError):
        content.attachments[0].name = "other"
