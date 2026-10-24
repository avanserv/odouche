"""The text and the attachments of a mail, read from its source. Nothing of it is fetched or rendered.

The source is parsed with `compat32`, whose header parsing takes a time in line with its size: the
default policy's takes minutes on one long `Cc` the build wrote. Each header is decoded from its
first `_MAX_HEADER` characters only, and the parts from the first `_MAX_PARTS`, for the same reason.
That count is of every MIME part, containers included.
"""

import email
import email.policy
import re
from contextlib import suppress
from dataclasses import dataclass
from email.errors import HeaderParseError
from email.header import decode_header, make_header
from email.message import Message
from html.parser import HTMLParser
from typing import cast, override

from odouche.models import MailAttachment


MAX_BODY = 1048576
"""The bytes of a body's text that are kept, as UTF-8."""

# The characters of an HTML body turned into text: what is past them would be cut from the text.
_MAX_HTML = 2 * MAX_BODY
# Decoding encoded words takes a time that grows with the square of the header's length.
_MAX_HEADER = 65536
# Every MIME part counts, a multipart container included.
_MAX_PARTS = 1000
_SKIPPED = frozenset({"script", "style", "head", "title"})
_BREAKS = frozenset({"br", "p", "div", "tr", "li", "table", "h1", "h2", "h3", "h4", "h5", "h6"})
_LINKED = ("http://", "https://")
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class Parsed:
    """What is read of a mail's source."""

    cc: str
    body: str
    attachments: tuple[MailAttachment, ...]
    truncated: bool


_UNREADABLE = Parsed(cc="", body="", attachments=(), truncated=True)


def parse(source: str) -> Parsed:
    """Read a mail's `Cc`, its text and its attachments. A source that cannot be read gives nothing, cut."""
    try:
        # As bytes: each part is then decoded with its own charset, and half of a surrogate pair is replaced.
        message = email.message_from_bytes(
            source.encode("utf-8", "replace"), _class=_Part, policy=email.policy.compat32
        )
        leaves, cut = _leaves(message)
        texts = [part for part in leaves if not _held(part)]
        body = next(
            (part for kind in ("text/plain", "text/html") for part in texts if part.get_content_type() == kind), None
        )
        attachments: list[MailAttachment] = []
        for part in leaves:
            if part is not body and (_held(part) or part.get_filename()):
                name, name_cut = _header(part.get_filename() or "")
                attachments.append(MailAttachment(name=name, size=len(_content(part))))
                cut = cut or name_cut
        cc, cc_cut = _header(next((value for key, value in message.raw_items() if key.lower() == "cc"), ""))
        text, text_cut = ("", False) if body is None else _text(body)
    # The mail was written by the build's code: whatever `email` raises on it is not upstream changing.
    except Exception:  # noqa: BLE001
        return _UNREADABLE
    kept = text.encode("utf-8", "replace")
    return Parsed(
        cc=cc,
        body=kept[:MAX_BODY].decode("utf-8", "ignore"),
        attachments=tuple(attachments),
        truncated=cut or cc_cut or text_cut or len(kept) > MAX_BODY,
    )


def html_text(html: str) -> str:
    """Return the text of an HTML body, a line for each block, with the address of each link after its text."""
    reader = _Reader()
    reader.feed(html)
    reader.close()
    kept: list[str] = []
    for line in "".join(reader.pieces).split("\n"):
        stripped = " ".join(line.split())
        # At most one blank line in a row, and none first.
        if stripped or (kept and kept[-1]):
            kept.append(stripped)
    return "\n".join(kept).strip("\n")


class _Part(Message):
    """A part whose content type is read once.

    The parser asks a part's type for each part inside it, and each ask walks its headers: a mail
    of many headers and many parts would take hours.
    """

    _type: str | None = None

    @override
    def set_raw(self, name: str, value: str) -> None:
        self._type = None
        super().set_raw(name, value)

    @override
    def set_default_type(self, ctype: str) -> None:
        self._type = None
        super().set_default_type(ctype)

    @override
    def get_content_type(self) -> str:
        if self._type is None:
            self._type = super().get_content_type()
        return self._type


def _leaves(message: Message) -> tuple[list[Message], bool]:
    """Return the parts of a mail that hold content, in order, and whether there were more than `_MAX_PARTS`.

    Every part walked counts toward `_MAX_PARTS`, a container included.

    An attached part is one, whatever it holds: a forwarded mail's text is not the mail's own.
    """
    leaves: list[Message] = []
    waiting = [message]
    for _ in range(_MAX_PARTS):
        if not waiting:
            return leaves, False
        part = waiting.pop()
        if part is not message and _held(part):
            leaves.append(part)
        elif part.is_multipart():
            waiting.extend(reversed(cast("list[Message]", part.get_payload())))
        else:
            leaves.append(part)
    return leaves, bool(waiting)


def _held(part: Message) -> bool:
    """Tell whether a part is attached to the mail, a forwarded one included, rather than part of its text."""
    return part.get_content_disposition() == "attachment" or part.get_content_maintype() == "message"


def _header(raw: str) -> tuple[str, bool]:
    """Return a header's text with its encoded words decoded, or as written when one cannot be, and whether it was cut."""
    # What `compat32` holds of the source's bytes that are not ASCII, back as the UTF-8 they are.
    text = raw.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
    cut = len(text) > _MAX_HEADER
    text = text[:_MAX_HEADER]
    with suppress(LookupError, UnicodeError, HeaderParseError):
        text = str(make_header(decode_header(text)))
    return _clean(text), cut


def _content(part: Message) -> bytes:
    """Return a part's bytes, decoded from its transfer encoding. A forwarded mail has none of its own."""
    return cast("bytes | None", part.get_payload(decode=True)) or b""


def _text(part: Message) -> tuple[str, bool]:
    """Return a part's text, from HTML when it is HTML, and whether it was cut before that."""
    content = _content(part)
    try:
        text = content.decode(part.get_content_charset() or "utf-8", "replace")
    except (LookupError, ValueError):
        # A charset Python does not know, or one that is not a name.
        text = content.decode("utf-8", "replace")
    if part.get_content_subtype() != "html":
        return _clean(text), False
    return html_text(_clean(text[:_MAX_HTML])), len(text) > _MAX_HTML


def _clean(text: str) -> str:
    """Replace what is not text: the JSON of an answer can hold half of a surrogate pair."""
    return text.encode("utf-8", "replace").decode()


class _Reader(HTMLParser):
    """Keeps the text of an HTML document, with a newline at each block. No address it holds is followed."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pieces: list[str] = []
        self._skipping = 0
        self._link: tuple[str, int] | None = None

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED:
            self._skipping += 1
        elif tag == "body":
            # A `head` nothing closed ends here.
            self._skipping = 0
        elif tag in _BREAKS:
            self.pieces.append("\n")
        elif tag == "a":
            href = dict(attrs).get("href") or ""
            self._link = (href, len(self.pieces)) if href.startswith(_LINKED) else None

    @override
    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED:
            self._skipping = max(self._skipping - 1, 0)
        elif tag in _BREAKS and tag != "br":
            self.pieces.append("\n")
        elif tag == "a" and self._link is not None:
            href, start = self._link
            self._link = None
            if " ".join("".join(self.pieces[start:]).split()) != href:
                self.pieces.append(f" <{href}>")

    @override
    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.pieces.append(_SPACE.sub(" ", data))
