"""The settings of a project, which its Settings page shows to an admin, and the request that changes them."""

import ipaddress
import math
import re
from collections import Counter
from dataclasses import dataclass, fields, replace

from odouche._upstream import projects, settings
from odouche._upstream.reader import Reader
from odouche._upstream.transport import Transport, state_changing
from odouche.errors import OdoucheError, SettingsConflictError
from odouche.models import ProjectSettings, ProjectSettingsChange, SessionLifetime, SettingsOutcome, Submodule


type _Entry = ipaddress.IPv4Address | ipaddress.IPv6Address | ipaddress.IPv4Network | ipaddress.IPv6Network

_OPERATION = "project settings"
_OPERATION_CHANGE = "project settings change"
# The keys of `session_lifetime_map`, in the slider's order.
_LIFETIMES = {
    "auto": SessionLifetime.AUTO,
    "4-hours": SessionLifetime.FOUR_HOURS,
    "8-hours": SessionLifetime.EIGHT_HOURS,
    "1-day": SessionLifetime.ONE_DAY,
    "2-days": SessionLifetime.TWO_DAYS,
    "4-days": SessionLifetime.FOUR_DAYS,
    "8-days": SessionLifetime.EIGHT_DAYS,
}
_LIFETIMES_SENT = {member: wire for wire, member in _LIFETIMES.items()}
# Each timeout's field in the form, which is also its key in `dedicated_limits`.
_LIMITS = {"http_timeout_seconds": "limit_real_time", "cron_timeout_seconds": "limit_real_time_cron"}
# The page's own bound: it says the list holds ten at most.
_MAX_ENTRIES = 10
_ALLOW_LIST = "ip_allow_list"
_ENTRIES = frozenset({"allow_ips", "disallow_ips"})
# What a change is checked against, named as in `ProjectSettings`: every setting but the name, the
# hosting figures, whose used storage moves by itself, and the submodules, which have requests of
# their own. Those the library does not send are compared too, since a section is sent in part.
_COMPARED = tuple(
    field.name for field in fields(ProjectSettings) if field.name not in {"name", "hosting", "submodules"}
)
# A key type, the key in base64, and an optional comment: nothing else, so that a private key never passes.
_PUBLIC_KEY = re.compile(r"(?:ssh|ecdsa|sk)-[A-Za-z0-9@.-]+ [A-Za-z0-9+/]+={0,2}(?: [^\x00-\x1f\x7f]*)?")


@dataclass(frozen=True, slots=True)
class _Limit:
    """A timeout's bounds as its page's input has them, in its unit of `unit` seconds."""

    unit: int
    low: int
    high: int
    value: float
    """The input's value, in the unit, as read."""


@dataclass(frozen=True, slots=True)
class _Page:
    """What the Settings page writes a change with, beyond the settings it shows."""

    lifetimes: tuple[str, ...]
    """The keys of `session_lifetime_map` in the answer's order, which the slider sends the index of."""
    limits: dict[str, _Limit]
    lines: tuple[str, ...]
    """The allow list as written, one entry a line, which is sent back so."""


def project_settings(transport: Transport, name: str) -> ProjectSettings:
    """Return the settings of the project named `name`. A value the library does not know is a changed shape."""
    technical = projects.admin(transport, name, _OPERATION, "Odoo.sh shows a project's settings to its admins only.")
    return _read(name, projects.settings_answer(transport, technical))


@state_changing
def change_settings(transport: Transport, name: str, change: ProjectSettingsChange) -> SettingsOutcome[ProjectSettings]:
    """Send the settings of `change` that differ from the project's, once, and return them before and after."""
    technical = projects.admin(
        transport, name, _OPERATION_CHANGE, "Odoo.sh lets only a project's admins change its settings."
    )
    answer = projects.settings_answer(transport, technical)
    current = _read(name, answer)
    narrowed = narrow(current, change)
    if narrowed is None:
        return SettingsOutcome(current, current, ())
    form = _form(narrowed, _page(answer))
    transport.change(_OPERATION_CHANGE, f"/app/project/{projects.segment(technical)}/set_settings", form)
    try:
        after = _read(name, projects.settings_answer(transport, technical))
    except OdoucheError:
        after = None
    sent = settings.Sent(_OPERATION_CHANGE, f"project {name}'s settings", _expected(current, narrowed))
    return settings.confirm(sent, current, after, _COMPARED, _same)


def narrow(current: ProjectSettings, change: ProjectSettingsChange) -> ProjectSettingsChange | None:
    """Return the part of `change` that differs from `current`, or `None`, refused as the Settings page refuses it.

    An address already allowed and an entry not listed are left out. Raises
    `SettingsConflictError` for a timeout on a project with no dedicated server, a new build
    option the page hides given the others after the change, and an allow list over ten entries.
    A timeout's unit and bounds are not in `current`: the change checks them before sending.
    """
    given = change.given()
    differs = {
        name: value for name, value in given.items() if name not in _ENTRIES and not settings.same(current, name, value)
    }
    allowed = tuple(address for address in change.allow_ips or () if address not in current.ip_allow_list)
    removed = tuple(entry for entry in change.disallow_ips or () if entry in current.ip_allow_list)
    if not differs and not allowed and not removed:
        return None
    if differs.keys() & _LIMITS.keys() and not current.dedicated:
        msg = "The timeouts are changed on a dedicated server only, and this project has none: its Settings page disables them."
        raise SettingsConflictError(msg)
    settings.check_options(differs.keys(), replace(current, **differs))  # pyright: ignore[reportArgumentType]
    _check_allow_list(current, allowed, removed)
    return replace(
        change,
        **dict.fromkeys(given.keys() - differs.keys() - _ENTRIES),
        allow_ips=allowed or None,
        disallow_ips=removed or None,
    )


def _check_allow_list(
    current: ProjectSettings,
    allowed: tuple[ipaddress.IPv4Address, ...],
    removed: tuple[ipaddress.IPv4Address | ipaddress.IPv6Address | ipaddress.IPv4Network | ipaddress.IPv6Network, ...],
) -> None:
    """Raise `SettingsConflictError` when entries are allowed and the list would then hold more than the page takes."""
    kept = [entry for entry in current.ip_allow_list if entry not in removed]
    if allowed and len(kept) + len(allowed) > _MAX_ENTRIES:
        msg = f"The allow list holds {_MAX_ENTRIES} entries at most, as its page says: remove some in the same change."
        raise SettingsConflictError(msg)


def _read(name: str, answer: Reader) -> ProjectSettings:
    repo = answer.child("repository")
    if repo.text("project_name") != name:
        raise repo.changed("project_name")
    limits = answer.child("dedicated_limits")
    return ProjectSettings(
        name=name,
        odoo_domain_blocked=repo.boolean("block_odoo_domain"),
        session_lifetime=settings.choice(answer, "session_lifetime", _LIFETIMES),
        public=not repo.boolean("private"),
        commit_statuses_suspended=repo.boolean("ci_suspended"),
        deploy_key_writable=repo.boolean("deploy_key_writable"),
        submodules=tuple(_submodule(item) for item in answer.items("submodules")),
        hosting=projects.hosting(answer),
        dedicated=repo.boolean("pays_dedicated"),
        http_timeout_seconds=_seconds(limits.child("limit_real_time")),
        cron_timeout_seconds=_seconds(limits.child("limit_real_time_cron")),
        module_install=settings.choice(repo, "modules_auto", settings.MODULES),
        modules=settings.modules(repo),
        tests=settings.choice(repo, "test_mode", settings.TESTS),
        test_tags=repo.optional_text("test_tags"),
        demo_data=repo.boolean("demo_data"),
        ai_agent=settings.choice(repo, "ai_agent", settings.AGENTS),
        ip_allow_list=_entries(repo),
    )


def _page(answer: Reader) -> _Page:
    lifetimes = answer.child("session_lifetime_map")
    keys = tuple(lifetimes.keys())
    # An index into another set of keys would set another lifetime than asked.
    if set(keys) != _LIFETIMES.keys():
        raise answer.changed("session_lifetime_map")
    limits = answer.child("dedicated_limits")
    return _Page(
        lifetimes=keys,
        limits={key: _limit(limits.child(key)) for key in _LIMITS.values()},
        lines=tuple(answer.child("repository").text("ip_whitelist").splitlines()),
    )


def _limit(limit: Reader) -> _Limit:
    # `min` and `max` are seconds, which the page's input divides by `unit_conversion` and rounds down.
    # The read of the settings has refused a `unit_conversion` under 1.
    unit = limit.integer("unit_conversion")
    low, high = limit.integer("min"), limit.integer("max")
    if not 0 <= low <= high:
        raise limit.changed("max")
    return _Limit(unit, low // unit, high // unit, limit.number("value"))


def _form(change: ProjectSettingsChange, page: _Page) -> dict[str, str]:
    """Return the parameters of a change, one for each setting it gives, as the page's sections send them."""
    sent = settings.option_params(change)
    if change.session_lifetime is not None:
        sent["session_lifetime"] = str(page.lifetimes.index(_LIFETIMES_SENT[change.session_lifetime]))
    if change.public is not None:
        sent["public"] = settings.flag(change.public)
    # The page sends its workers section whole: a limit not given goes with its value as read.
    if any(getattr(change, name) is not None for name in _LIMITS):
        for name, key in _LIMITS.items():
            seconds: int | None = getattr(change, name)
            limit = page.limits[key]
            sent[key] = format(limit.value, "g") if seconds is None else str(_units(name, seconds, limit))
    if change.allow_ips is not None or change.disallow_ips is not None:
        removed = change.disallow_ips or ()
        kept = [line for line in page.lines if line.strip() and _entry(line.strip()) not in removed]
        sent["ip_whitelist"] = "\n".join([*kept, *map(str, change.allow_ips or ())])
    return sent


def _units(name: str, seconds: int, limit: _Limit) -> int:
    units, rest = divmod(seconds, limit.unit)
    if rest or not limit.low <= units <= limit.high:
        msg = (
            f"`{name}` is a multiple of {limit.unit} seconds from {limit.low * limit.unit} to "
            f"{limit.high * limit.unit} on this project, as its Settings page takes it."
        )
        raise SettingsConflictError(msg)
    return units


def _expected(current: ProjectSettings, change: ProjectSettingsChange) -> dict[str, object]:
    """Return the settings a change is to show once read back, by their name in `ProjectSettings`."""
    expected = {name: value for name, value in change.given().items() if name not in _ENTRIES}
    if change.allow_ips is not None or change.disallow_ips is not None:
        removed = change.disallow_ips or ()
        kept = tuple(entry for entry in current.ip_allow_list if entry not in removed)
        expected[_ALLOW_LIST] = kept + (change.allow_ips or ())
    return expected


def _same(read: ProjectSettings, name: str, value: object) -> bool:
    if name == _ALLOW_LIST:
        # Whatever order Odoo.sh keeps them in.
        return Counter(read.ip_allow_list) == Counter(value) if isinstance(value, tuple) else False
    return settings.same(read, name, value)


def _submodule(item: Reader) -> Submodule:
    # No local of this frame holds a key that failed the test.
    public_key = _public_key(item.text("deploy_key_public"))
    if public_key is None:
        raise item.changed("deploy_key_public")
    return Submodule(
        id=item.integer("id"),
        url=item.text("name"),
        fingerprint=item.text("deploy_key_public_fingerprint"),
        public_key=public_key,
    )


def _public_key(text: str) -> str | None:
    # As `ssh-keygen` writes a `.pub` file: one line, which may end with its line break.
    line = text.removesuffix("\n").removesuffix("\r")
    return line if _PUBLIC_KEY.fullmatch(line) else None


def _seconds(limit: Reader) -> int:
    # The value is in the page's unit, minutes in the capture, which `unit_conversion` turns into seconds.
    value = limit.number("value")
    if not 0 <= value < math.inf:
        raise limit.changed("value")
    conversion = limit.integer("unit_conversion")
    if conversion < 1:
        raise limit.changed("unit_conversion")
    return round(value * conversion)


def _entries(repo: Reader) -> tuple[_Entry, ...]:
    try:
        return tuple(_entry(entry) for entry in map(str.strip, repo.text("ip_whitelist").splitlines()) if entry)
    except ValueError:
        # Its message quotes the entry.
        raise repo.changed("ip_whitelist") from None


def _entry(text: str) -> _Entry:
    # Each as written, so that it can be sent back so. What Odoo.sh accepts beyond the page's IPv4s is unseen.
    return ipaddress.ip_network(text, strict=False) if "/" in text else ipaddress.ip_address(text)
