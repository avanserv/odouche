"""The settings of a project, which its Settings page shows to an admin."""

import ipaddress
import math
import re

from odouche._upstream import projects, settings
from odouche._upstream.reader import Reader
from odouche._upstream.transport import Transport
from odouche.errors import PermissionDeniedError
from odouche.models import ProjectSettings, SessionLifetime, Submodule


_OPERATION = "project settings"
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
# A key type, the key in base64, and an optional comment: nothing else, so that a private key never passes.
_PUBLIC_KEY = re.compile(r"(?:ssh|ecdsa|sk)-[A-Za-z0-9@.-]+ [A-Za-z0-9+/]+={0,2}(?: [^\x00-\x1f\x7f]*)?")


def project_settings(transport: Transport, name: str) -> ProjectSettings:
    """Return the settings of the project named `name`. A value the library does not know is a changed shape."""
    info = projects.info(transport, name)
    active = info.child("active_repo")
    if active.text("project_name") != name:
        raise active.changed("project_name")
    # The page's own test: what Odoo.sh answers anyone else was never seen.
    if not projects.is_admin(info):
        raise PermissionDeniedError("Odoo.sh shows a project's settings to its admins only.", operation=_OPERATION)
    answer = projects.settings_answer(transport, active.text("technical_name"))
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


def _entries(
    repo: Reader,
) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address | ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    # Each as written, so that it can be sent back so. What Odoo.sh accepts beyond the page's IPv4s is unseen.
    try:
        return tuple(
            ipaddress.ip_network(entry, strict=False) if "/" in entry else ipaddress.ip_address(entry)
            for entry in map(str.strip, repo.text("ip_whitelist").splitlines())
            if entry
        )
    except ValueError:
        # Its message quotes the entry.
        raise repo.changed("ip_whitelist") from None
