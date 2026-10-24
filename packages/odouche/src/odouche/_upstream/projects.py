"""The projects request, and the info and settings of one project."""

import logging
import re
from urllib.parse import quote

from odouche._upstream.reader import Reader
from odouche._upstream.transport import Transport
from odouche.errors import PermissionDeniedError
from odouche.models import ProductionBuild, Project, ProjectHosting, Subscription
from odouche.secret import Secret


PATH = "/app/projects"

_OPERATION = "projects"
_INFO = "project"
_SETTINGS = "project settings"
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*")
_SSH_SCHEMES = frozenset({"ssh", "git+ssh", "ssh+git"})
# A Unix user name and nothing else: no password, no token after a colon.
_SSH_USER = re.compile(r"[a-z_][a-z0-9_-]{0,31}")
# What GitHub and GitLab tokens start with, which a user name of that shape can still be.
_TOKEN_PREFIXES = ("ghp_", "gho_", "ghu_", "ghs_", "ghr_", "github_pat_", "glpat-", "x-access-token")
# A host, or a bracketed IPv6 address, then an optional port.
_AUTHORITY = re.compile(r"(?:[A-Za-z0-9.-]+|\[[0-9A-Fa-f:.]+\])(?::[0-9]*)?")
# The page's templates name `trial`, `custom` and `invalid`: only `valid` was seen.
_SUBSCRIPTIONS = {
    "valid": Subscription.VALID,
    "trial": Subscription.TRIAL,
    "custom": Subscription.NON_STANDARD,
    "invalid": Subscription.EXPIRED,
}

_logger = logging.getLogger("odouche")


def projects(transport: Transport) -> list[Project]:
    """List the projects the session's user can reach. Odoo.sh answers them all at once."""
    return [
        Project(
            id=repo.integer("id"),
            name=repo.text("project_name"),
            repository=f"{repo.text('owner')}/{repo.text('name')}",
            url=repo.text("project_url"),
        )
        for repo in _repos(transport)
    ]


def technical_name(transport: Transport, name: str) -> str | None:
    """Return the name a project's other requests address it by, or `None` when it is not listed."""
    for repo in _repos(transport):
        if repo.text("project_name") == name:
            return repo.text("technical_name")
    return None


def project_id(transport: Transport, name: str, *, within: float | None = None) -> int | None:
    """Return the number of the project named `name`, or `None` when it is not listed."""
    for repo in _repos(transport, within):
        if repo.text("project_name") == name:
            return repo.integer("id")
    return None


def odoo_version(transport: Transport, name: str) -> str | None:
    """Return the Odoo version of the project named `name`, such as `19.0`, or `None` when it is not listed."""
    for repo in _repos(transport):
        if repo.text("project_name") == name:
            return repo.text("odoo_branch")
    return None


def segment(name: str) -> str:
    """Quote a name for the address of a request. A dot is quoted too: the client resolves `..`."""
    return quote(name, safe="").replace(".", "%2E")


def access_token(transport: Transport, name: str) -> Secret:
    """Return the token the workers of the project named `name` take. It opens every build's logs."""
    result = Reader(_INFO, _get_info(transport, name)).child("result")
    token = result.text("access_token")
    if not token:
        raise result.changed("access_token")
    return Secret(token)


def region(transport: Transport, name: str) -> str | None:
    """Return where the project named `name` is hosted, such as `Europe`, or `None` when it is not listed."""
    for repo in _repos(transport):
        if repo.text("project_name") == name:
            return repo.text("geolocation")
    return None


def info(transport: Transport, name: str, *, within: float | None = None) -> Reader:
    """Return the reader of a project's info. Its token and its codes are dropped unread."""
    body = _get_info(transport, name, within)
    _drop(body, ("result",), "access_token")
    return Reader(_INFO, body).child("result")


def subscription(repo: Reader) -> tuple[Subscription, str]:
    """Return the state of a project's subscription and what Odoo.sh calls it."""
    name = repo.text("subscription_validity")
    known = _SUBSCRIPTIONS.get(name)
    if known is None:
        _logger.debug("Unknown subscription state: %r", name)
        return Subscription.UNKNOWN, name
    return known, name


def production_build(repo: Reader) -> ProductionBuild | None:
    """Return the build a project's production branch serves, or `None` when there is none."""
    build = repo.optional_child("production_build_id")
    if build is None:
        return None
    return ProductionBuild(id=build.integer("id"), branch_name=build.text("branch_name"), url=build.text("url"))


def is_admin(info: Reader) -> bool:
    """Tell whether the session's user is an admin of the project, by the test its page makes."""
    levels = info.child("config").child("access_level_map")
    return levels.integer(info.child("user").text("access")) >= levels.integer("admin")


def admin(transport: Transport, name: str, operation: str, refusal: str) -> str:
    """Return the name a project's requests address it by, once its info shows the session's user is an admin of it."""
    read = info(transport, name)
    active = read.child("active_repo")
    if active.text("project_name") != name:
        raise active.changed("project_name")
    # The page's own test: what Odoo.sh answers anyone else was never seen.
    if not is_admin(read):
        raise PermissionDeniedError(refusal, operation=operation)
    return active.text("technical_name")


def settings_answer(transport: Transport, technical_name: str) -> Reader:
    """Return the reader of the `result` of a project's settings.

    Its token, its codes, the subscription link that carries one, and the credentials, query and fragment of
    each submodule URL are dropped unread.
    """
    body = transport.call(_SETTINGS, f"/app/project/{segment(technical_name)}/get_settings", retry=True)
    _drop(body, ("result", "repository"), "ci_token", "subscription_code", "subscription_code_display")
    # Whole, as nothing reads it: its subscription link carries the code as a query value.
    _drop(body, ("result",), "upsells")
    result = body.get("result")
    submodules = result.get("submodules") if isinstance(result, dict) else None
    for submodule in submodules if isinstance(submodules, list) else []:
        _drop_credentials(submodule, "name")
    return Reader(_SETTINGS, body).child("result")


def hosting(answer: Reader) -> ProjectHosting:
    """Return what the Settings page of a project shows of its storage and workers, from its settings' `result`."""
    repo = answer.child("repository")
    return ProjectHosting(
        storage_used_bytes=_bytes(repo, "used_storage"),
        storage_quota_bytes=_bytes(repo, "max_storage"),
        workers=repo.integer("max_production_workers"),
        staging_branches=repo.integer("max_staging_branches"),
    )


def _get_info(transport: Transport, name: str, within: float | None = None) -> dict[str, object]:
    body = transport.call(
        _INFO,
        f"/app/project/{segment(name)}/get_info",
        retry=True,
        not_found=f"The session's user can reach no project named {name!r}.",
        within=within,
    )
    _drop(body, ("result", "active_repo"), "subscription_code")
    _drop(body, ("result", "active_repo", "production_build_id"), "enterprise_code")
    return body


def _drop(body: object, path: tuple[str, ...], *keys: str) -> None:
    # Popped before anything is read, so that no reader, frame or error holds them.
    fields = body
    for step in path:
        fields = fields.get(step) if isinstance(fields, dict) else None
    if isinstance(fields, dict):
        for key in keys:
            fields.pop(key, None)


def _drop_credentials(fields: object, key: str) -> None:
    # Before anything is read. The user information ends at the last `@` before the path: the first `/`
    # after `//` in a URL, the first `/` at all in an scp-like `user@host:path`.
    url = fields.get(key) if isinstance(fields, dict) else None
    if not isinstance(fields, dict) or not isinstance(url, str):
        return
    url = re.split(r"[?#]", url, maxsplit=1)[0]
    scheme, separator, rest = url.partition("://")
    if not separator:
        scheme, rest = "", url
    head, slash, path = rest.partition("/")
    user, at, host = head.rpartition("@")
    if separator and (not _SCHEME.fullmatch(scheme) or not _AUTHORITY.fullmatch(host) or (":" in user and "@" in path)):
        # What is left could still hold part of a password, such as one with a `/`: the value goes whole.
        fields[key] = ""
        return
    # An scp-like `user@host:path` is SSH too.
    ssh = scheme.lower() in _SSH_SCHEMES if separator else True
    kept = f"{user}@" if at and ssh and _ssh_user(user) else ""
    fields[key] = f"{scheme}{separator}{kept}{host}{slash}{path}"


def _ssh_user(user: str) -> bool:
    return bool(_SSH_USER.fullmatch(user)) and not user.startswith(_TOKEN_PREFIXES)


def _bytes(repo: Reader, key: str) -> int:
    # Sizes are KiB: the page shows them with `humanSize(size * 1024)`.
    value = repo.number(key)
    if value < 0:
        raise repo.changed(key)
    return round(value * 1024)


def _repos(transport: Transport, within: float | None = None) -> list[Reader]:
    body = transport.call(_OPERATION, PATH, retry=True, within=within)
    result = body.get("result")
    repos = result.get("repos") if isinstance(result, dict) else None
    for repo in repos if isinstance(repos, list) else []:
        _drop(repo, (), "subscription_code")
    return Reader(_OPERATION, body).child("result").items("repos")
