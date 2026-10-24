"""What the library returns: its own models, not the payloads of Odoo.sh."""

import re
from collections.abc import Iterator
from dataclasses import dataclass, fields
from datetime import datetime
from enum import StrEnum

from odouche.errors import OdoucheError


@dataclass(frozen=True, slots=True)
class Project:
    """An Odoo.sh project the session's user can reach."""

    id: int
    """The number Odoo.sh gives the project."""

    name: str
    """The project's name on Odoo.sh, as in the address of its page."""

    repository: str
    """The GitHub repository the project builds, as `owner/name`."""

    url: str
    """The address of the project's page on Odoo.sh."""


class Stage(StrEnum):
    """The stage a branch sits in on Odoo.sh."""

    PRODUCTION = "production"
    STAGING = "staging"
    DEVELOPMENT = "development"
    UNKNOWN = "unknown"
    """A stage the library does not know. The branch's `stage_name` holds what Odoo.sh calls it."""


@dataclass(frozen=True, slots=True)
class Branch:
    """A branch of an Odoo.sh project."""

    id: int
    """The number Odoo.sh gives the branch."""

    name: str
    """The git branch."""

    stage: Stage
    """The stage the branch sits in now."""

    stage_name: str
    """What Odoo.sh calls that stage, such as `dev`."""


class BuildStatus(StrEnum):
    """Where a build is in its life on Odoo.sh. How it ended is its `BuildResult`."""

    PROGRESS = "progress"
    UPDATING = "updating"
    DONE = "done"
    DROPPED = "dropped"
    """What a build becomes when a newer one replaces it."""
    SKIPPED = "skipped"
    KILLED = "killed"
    UNKNOWN = "unknown"
    """A status the library does not know. The build's `status_name` holds what Odoo.sh calls it."""


class BuildResult(StrEnum):
    """How a build ended."""

    SUCCESS = "success"
    FAILED = "failed"
    WARNING = "warning"
    UNKNOWN = "unknown"
    """A result the library does not know. The build's `result_name` holds what Odoo.sh calls it."""


_FINISHED = frozenset({BuildStatus.DONE, BuildStatus.DROPPED, BuildStatus.SKIPPED, BuildStatus.KILLED})


@dataclass(frozen=True, slots=True)
class Commit:
    """The commit a build was made from, as Odoo.sh reports it."""

    hash: str
    """The commit's full hash."""

    message: str
    """The whole commit message."""

    author: str
    """The author's name. It is another person's personal data, carried as Odoo.sh gives it."""

    timestamp: datetime
    """When the commit was made, in UTC."""

    url: str
    """The address of the commit on GitHub."""


@dataclass(frozen=True, slots=True)
class Build:
    """What Odoo.sh made of a commit on a branch."""

    id: int
    """The number Odoo.sh gives the build."""

    name: str
    """The build's name on Odoo.sh, which is not derivable from its branch."""

    branch_id: int
    """The number of the branch the build belongs to."""

    branch_name: str
    """The git branch."""

    commit: Commit
    """The commit the build was made from."""

    status: BuildStatus
    """Where the build is in its life."""

    status_name: str
    """What Odoo.sh calls that status, such as `progress`."""

    result: BuildResult | None
    """How the build ended, or `None` when Odoo.sh gives none. `finished` says whether it ended."""

    result_name: str | None
    """What Odoo.sh calls that result, such as `success`."""

    status_info: str | None
    """What the build is doing, in Odoo.sh's own words, such as `Installing: account`."""

    started_at: datetime | None
    """When a worker took the build, in UTC, or `None` while it waits for one."""

    url: str | None
    """The address of the build's database, when it has one."""

    @property
    def finished(self) -> bool:
        """Whether the build has ended, whatever its result.

        `DONE` and `DROPPED` are the ended statuses Odoo.sh has been seen to give. `SKIPPED` and
        `KILLED` are counted as ended from their names alone. An unknown status is not finished.
        """
        return self.status in _FINISHED


@dataclass(frozen=True, slots=True)
class OdooRef:
    """The commit of one of Odoo's own repositories in a weekly Odoo revision."""

    repository: str
    """What Odoo.sh calls the repository, such as `enterprise`."""

    commit_hash: str
    """The commit's full hash."""

    url: str
    """The repository's address."""


@dataclass(frozen=True, slots=True)
class OdooRevision:
    """A weekly revision of Odoo's own repositories, as a branch has selected it."""

    id: int
    """The number Odoo.sh gives the revision, which `BranchSettings.odoo_revision_id` holds when it is pinned."""

    version: str
    """The Odoo version, such as `19.0`."""

    pinned: bool
    """Whether the branch pins this revision. Otherwise it is the latest of its version, and moves on."""

    refs: tuple[OdooRef, ...]
    """The commit of each repository, in the order Odoo.sh gives them."""


@dataclass(frozen=True, slots=True)
class BuildRevision:
    """What a build runs, as far as Odoo.sh says.

    Odoo.sh gives no commit for a submodule of the project's repository, so there is none here,
    and nothing here says whether the repository has any.
    """

    build_id: int
    """The number Odoo.sh gives the build."""

    build_name: str
    """The build's name on Odoo.sh."""

    branch_name: str
    """The git branch."""

    commit: Commit
    """The head commit of the project's repository, with its full hash."""

    odoo_version: str
    """The Odoo version the build was made with, such as `19.0`."""

    branch_odoo_revision: OdooRevision | None
    """The Odoo revision the branch has selected now, or `None` when Odoo.sh gives none.

    Odoo.sh ties no revision to a build, so it is not proven to be the one the build runs.
    """


class TrackingKind(StrEnum):
    """What happened to a branch, as its history on Odoo.sh records it."""

    PUSH = "push"
    REBUILD = "rebuild"
    STAGE = "stage"
    """The branch was created in a stage or moved to another."""
    UNKNOWN = "unknown"
    """An event the library does not know. The tracking's `kind_name` holds what Odoo.sh calls it."""


@dataclass(frozen=True, slots=True)
class PushedCommit:
    """A commit of a push, as the history gives it: with no author and no date."""

    hash: str
    """The commit's full hash."""

    message: str
    """The whole commit message."""

    url: str
    """The address of the commit on GitHub."""


@dataclass(frozen=True, slots=True)
class TrackedBuild:
    """A build as a summary gives it: its number, status and result, for an event of a branch's history or a
    branch's last build. `Client.build` has the rest of it.
    """

    id: int
    """The number Odoo.sh gives the build."""

    status: BuildStatus
    """Where the build is in its life."""

    status_name: str
    """What Odoo.sh calls that status, such as `progress`."""

    result: BuildResult | None
    """How the build ended, or `None` when Odoo.sh gives none."""

    result_name: str | None
    """What Odoo.sh calls that result, such as `success`."""


@dataclass(frozen=True, slots=True)
class Tracking:
    """One event of a branch's history: a push, a rebuild or a move between stages."""

    id: int
    """The number Odoo.sh gives the event."""

    kind: TrackingKind
    """What happened."""

    kind_name: str
    """What Odoo.sh calls it, such as `push`."""

    created_at: datetime
    """When it happened, in UTC."""

    build: TrackedBuild | None
    """The build it made, or `None`, as for the stage event that created the branch."""

    commits: tuple[PushedCommit, ...]
    """The commits of a push, in the order Odoo.sh gives them. Empty for any other event."""

    pusher: str | None
    """Who pushed, as Odoo.sh names them. It is another person's personal data, carried as given."""

    source_stage: Stage | None
    """The stage a branch moved from, or `None`, as for one just created or any event but a move."""

    target_stage: Stage | None
    """The stage a branch moved to or was created in, or `None` for any event but a stage one."""


class Subscription(StrEnum):
    """The state of a project's subscription, as Odoo.sh reports it."""

    VALID = "valid"
    TRIAL = "trial"
    NON_STANDARD = "non_standard"
    """A subscription Odoo.sh calls `custom`, which its page shows as non-standard."""
    EXPIRED = "expired"
    """A subscription Odoo.sh calls `invalid`, which its page shows as expired."""
    UNKNOWN = "unknown"
    """A state the library does not know. The overview's `subscription_name` holds what Odoo.sh calls it."""


@dataclass(frozen=True, slots=True)
class ProductionBuild:
    """The build a project's production branch serves."""

    id: int
    """The number Odoo.sh gives the build."""

    branch_name: str
    """The git branch."""

    url: str
    """The address of the production database."""


@dataclass(frozen=True, slots=True)
class ProjectHosting:
    """What a project's subscription allows and how much storage it uses, as its Settings page shows them."""

    storage_used_bytes: int
    """The storage the project is accounted for, in bytes."""

    storage_quota_bytes: int
    """The storage the subscription allows, in bytes."""

    workers: int
    """The workers of the production branch."""

    staging_branches: int
    """The staging branches the subscription allows."""


@dataclass(frozen=True, slots=True)
class StageCount:
    """How many branches of a project sit in one stage."""

    stage: Stage
    """The stage."""

    stage_name: str
    """What Odoo.sh calls that stage, such as `dev`."""

    count: int
    """The branches in it, which can be 0."""


@dataclass(frozen=True, slots=True)
class BranchSummary:
    """A branch of a project, with its last build."""

    branch: Branch
    """The branch."""

    last_build: TrackedBuild | None
    """Its last build, or `None` when it has none."""


@dataclass(frozen=True, slots=True)
class ProjectOverview:
    """What a project's page and its Settings page tell about it. No token or code is part of it."""

    id: int
    """The number Odoo.sh gives the project."""

    name: str
    """The project's name on Odoo.sh, as in the address of its page."""

    repository: str
    """The GitHub repository the project builds, as `owner/name`."""

    subscription: Subscription
    """The state of the project's subscription."""

    subscription_name: str
    """What Odoo.sh calls that state, such as `valid`."""

    trial_days_left: int | None
    """The days left of a trial given by a partnership code, or `None` when there is none."""

    odoo_version: str
    """The project's Odoo version, such as `19.0`."""

    region: str
    """Where the project is hosted, in Odoo.sh's own words, such as `Europe`."""

    dedicated: bool
    """Whether the project pays for a dedicated server."""

    production_build: ProductionBuild | None
    """The build the production branch serves, or `None` when there is none."""

    access_level: str
    """What the session's user is on the project, in Odoo.sh's own words, such as `admin` or `developer`."""

    hosting: ProjectHosting | None
    """Its storage, workers and staging branches, or `None` when the session's user is not an admin of
    the project: Odoo.sh shows them to an admin only, and they are not asked otherwise.
    """

    stages: tuple[StageCount, ...]
    """The branches in production, staging and development, each counted even at 0, then in each stage the
    library does not know, by name.
    """

    branches: tuple[BranchSummary, ...]
    """The branches with their last builds, in the order Odoo.sh answers them."""


class AuditKind(StrEnum):
    """What a project's audit log records someone did."""

    ALLOW_IP = "allow_ip"
    CONNECT_AS_USER = "connect_as_user"
    DOWNLOAD_DATABASE = "download_database"
    MANAGE_COLLABORATORS = "manage_collaborators"
    OPEN_EDITOR = "open_editor"
    OPEN_SHELL = "open_shell"
    OPEN_WEBMAIL = "open_webmail"
    OPEN_DATABASE_LOGS = "open_database_logs"
    CHANGE_BRANCH_STAGE = "change_branch_stage"
    ADD_DOMAIN_NAME = "add_domain_name"
    MANAGE_SETTINGS = "manage_settings"
    UNKNOWN = "unknown"
    """An action the library does not know. The entry's `kind_name` holds what Odoo.sh calls it."""


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """One entry of a project's audit log: who did what, when, and on which stage."""

    logged_at: datetime
    """When it was done, in UTC."""

    author: str
    """Who did it, as a GitHub login. It is another person's personal data, carried as given, which can hold
    control characters.
    """

    kind: AuditKind
    """What was done."""

    kind_name: str
    """What Odoo.sh calls it, such as `Open Shell`, cut to 64 characters. Text Odoo.sh sends, not checked."""

    stage: Stage | None
    """The stage of the branch it was done on, or `None` for an action on the project."""

    details: str
    """What Odoo.sh adds about it, often empty. It holds addresses, logins and what an SSH client says of
    itself: untrusted text, carried as given, which can hold control characters.
    """

    succeeded: bool
    """Whether it succeeded."""


class PushBehavior(StrEnum):
    """What a new commit on a branch does."""

    NOTHING = "nothing"
    NEW_BUILD = "new_build"
    """A new build, with a new database."""
    UPDATE = "update"
    """The latest build is updated with the commit, and keeps its database."""


class ModuleInstall(StrEnum):
    """Which modules a new build installs."""

    REPOSITORY = "repository"
    """The modules of the project's repository."""
    ALL = "all"
    """The standard Odoo modules and the repository's. The page says it turns the test suite off."""
    LISTED = "listed"
    """The modules of the settings' `modules`."""


class BuildTests(StrEnum):
    """Which tests a new build runs."""

    OFF = "off"
    MODULES = "modules"
    """The tests of the modules it installs."""
    TAGS = "tags"
    """Those the settings' `test_tags` select."""


class AiAgent(StrEnum):
    """The agent a branch's AI tab runs."""

    CLAUDE = "claude"
    OPENCODE = "opencode"


@dataclass(frozen=True, slots=True)
class BranchSettings:
    """A branch's settings, as its Settings tab shows them.

    The new build options, `project_defaults` to `ai_agent`, apply to a development branch only.
    The project's development defaults are not read here.
    """

    push_behavior: PushBehavior
    """What a new commit does."""

    project_defaults: bool
    """Whether the project's development defaults apply instead of the next six fields, which the page then disables."""

    module_install: ModuleInstall
    """Which modules a new build installs."""

    modules: tuple[str, ...]
    """The modules stored for `LISTED`, given whatever `module_install` is. They apply only to `LISTED`."""

    tests: BuildTests
    """Which tests a new build runs."""

    test_tags: str | None
    """The Odoo test tags stored for `TAGS`, given whatever `tests` is. They apply only to `TAGS`."""

    demo_data: bool
    """Whether a new build loads demonstration data."""

    ai_agent: AiAgent
    """The agent the AI tab runs."""

    odoo_version: str | None
    """The Odoo version, such as `19.0`, or `None` for the project's."""

    odoo_revision_id: int | None
    """The id Odoo.sh gives the pinned weekly Odoo revision, or `None` for the latest. Its name is not given."""

    machine: str
    """The operating system builds run on, such as `ubuntu-24.04`."""

    recommended_machine: str
    """The operating system Odoo.sh recommends."""

    next_machine: str | None
    """The operating system the next commit's build moves to, or `None`. Only `None` was seen."""

    domains: tuple[str, ...]
    """The custom domains."""

    dns_target: str | None
    """The host a custom domain's CNAME record points to."""


_MODULE = re.compile(r"[A-Za-z0-9_]+")
# The characters of Odoo's `--test-tags`: `[-][tag][/module][:class][.method][[params]]`, separated by commas.
_TEST_TAGS = re.compile(r"[A-Za-z0-9_/:.,*+\-\[\]]*")
# What each field of a change is given as.
_KINDS: dict[str, type] = {
    "push_behavior": PushBehavior,
    "project_defaults": bool,
    "module_install": ModuleInstall,
    "modules": tuple,
    "tests": BuildTests,
    "test_tags": str,
    "demo_data": bool,
    "ai_agent": AiAgent,
}


@dataclass(frozen=True, slots=True, kw_only=True)
class SettingsChange:
    """Settings to change on a branch, named as in `BranchSettings`: a field left `None` keeps its value on Odoo.sh.

    Raises `ValueError` when no field is given, for a module name of anything but ASCII letters,
    digits and underscores, and for test tags of other characters than Odoo's tags have, and
    `TypeError` for a value of another type, such as a choice given as text rather than as its
    enum's member.
    """

    push_behavior: PushBehavior | None = None
    """What a new commit does."""

    project_defaults: bool | None = None
    """Whether the project's development defaults apply instead of the branch's own new build options."""

    module_install: ModuleInstall | None = None
    """Which modules a new build installs."""

    modules: tuple[str, ...] | None = None
    """The modules a new build installs with `LISTED`."""

    tests: BuildTests | None = None
    """Which tests a new build runs."""

    test_tags: str | None = None
    """The Odoo test tags `TAGS` runs. An empty text clears them."""

    demo_data: bool | None = None
    """Whether a new build loads demonstration data."""

    ai_agent: AiAgent | None = None
    """The agent the AI tab runs."""

    def __post_init__(self) -> None:
        given = self.given()
        if not given:
            msg = "A change of settings names at least one setting."
            raise ValueError(msg)
        for name, value in given.items():
            _check_setting(name, value)

    def given(self) -> dict[str, object]:
        """Return the settings given, by name, in the order of the fields."""
        return {field.name: value for field in fields(self) if (value := getattr(self, field.name)) is not None}


@dataclass(frozen=True, slots=True)
class SettingsOutcome:
    """What a change of a branch's settings did: the settings before and after it."""

    before: BranchSettings
    """The settings read before the change."""

    after: BranchSettings
    """The settings read back after it, which show every setting sent as sent."""

    moved: tuple[str, ...]
    """The settings not sent that Odoo.sh changed along with those sent, such as the tests a new
    build runs once it installs every module. `before` and `after` hold their values."""


def _check_setting(name: str, value: object) -> None:
    kind = _KINDS[name]
    # `bool` is checked exactly: an `int` is not a yes or a no.
    if not (type(value) is kind if kind is bool else isinstance(value, kind)):
        msg = f"`{name}` is given as a {kind.__name__}."
        raise TypeError(msg)
    if isinstance(value, tuple):
        for module in value:
            # A comma would split the name in two once sent, and a space or a control character is no module's.
            if not isinstance(module, str) or not _MODULE.fullmatch(module):
                msg = f"{module!r} is not a module name: one has only ASCII letters, digits and underscores."
                raise ValueError(msg)
    # What Odoo.sh does with the text is not seen: it is held to what Odoo reads as tags.
    if name == "test_tags" and isinstance(value, str) and not _TEST_TAGS.fullmatch(value):
        msg = "Test tags hold only ASCII letters, digits and `_/:.,*+-[]`."
        raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class SshTarget:
    """Where `ssh` reaches a build: the user to log in as and the host."""

    user: str
    """The user on the build's host, which is the build's number."""

    host: str
    """The build's own host."""


class Panel(StrEnum):
    """A page of a build that Odoo.sh opens in a browser."""

    MONITOR = "monitor"
    """The branch's Grafana dashboard on `www.odoo.sh`, for a staging or a production branch."""
    SHELL = "shell"
    """A terminal in the build's container, on its own host."""
    EDITOR = "editor"
    """The code editor of the build's container, on its own host."""


class LogKind(StrEnum):
    """The logs Odoo.sh keeps of a build. A build has only some of them."""

    INSTALL = "install"
    PIP = "pip"
    ODOO = "odoo"
    UPDATE = "update"
    NEUTRALIZE = "neutralize"
    UPGRADE = "upgrade"
    UNKNOWN = "unknown"
    """A log the library does not know. The log's `name` holds what Odoo.sh calls it."""


@dataclass(frozen=True, slots=True)
class Log:
    """One of the logs a build has."""

    kind: LogKind
    """Which log it is."""

    name: str
    """What Odoo.sh calls it, such as `install`."""

    modified_at: datetime
    """When it was last written to, in UTC."""

    size: str
    """Its size in Odoo.sh's own words, such as `156 KB`."""


@dataclass(frozen=True, slots=True)
class LogLine:
    """A line of a build's log. It is untrusted: whatever a process printed, unchanged."""

    text: str
    """The line without its newline. Bytes that are not UTF-8 are replaced."""

    offset: int
    """The byte just past the line, which is where a follow can start again."""

    truncated: bool
    """Whether the line was longer than the library reads, and was cut."""


@dataclass(frozen=True, slots=True)
class Mail:
    """A mail a build caught instead of sending it. Every field but `id` is untrusted: the build's code or its data wrote it."""

    id: str
    """The worker's name for the mail, which `Client.mail` takes."""

    date: datetime | None
    """When the mail is dated, in UTC, or `None` when `date_text` is not a date the library reads."""

    date_text: str
    """The date as the worker gives it."""

    sender: str
    """The `From` header, as written."""

    recipients: str
    """The `To` header, as written: every address, comma-separated."""

    subject: str
    """The `Subject` header, as written."""


@dataclass(frozen=True, slots=True)
class MailAttachment:
    """A file attached to a caught mail. Its name is untrusted, and its content is not read."""

    name: str
    """Its file name, as the mail gives it. Empty when it has none."""

    size: int
    """Its bytes, decoded. A forwarded mail counts none: its parts are not read."""


@dataclass(frozen=True, slots=True)
class MailContent:
    """One caught mail with its body. The body and the names are untrusted text, never rendered."""

    mail: Mail
    """The mail as `Client.mails` lists it."""

    cc: str
    """The `Cc` header, as written. Empty when it has none."""

    body: str
    """The plain text part, or the HTML part as text. Never rendered."""

    attachments: tuple[MailAttachment, ...]
    """The files attached to it."""

    truncated: bool
    """Whether anything was cut: the body at 1 MiB as UTF-8, a header at 65536 characters, or the parts at 1000.

    The 1000 count every MIME part, containers included. Also when the mail was over 16 MiB or could not be read: then `body` and `attachments` are empty.
    """


class BackupKind(StrEnum):
    """How a backup was made, and where it is kept."""

    MANUAL = "manual"
    """Asked for on a branch, and kept for three days."""
    DAILY = "daily"
    REMOTE = "remote"
    """A daily backup kept off-site. Odoo.sh does not let it be downloaded as it is."""
    UNKNOWN = "unknown"
    """A kind the library does not know. The backup's `kind_name` holds what Odoo.sh calls it."""


@dataclass(frozen=True, slots=True)
class Backup:
    """A backup of a project's database, on any of its branches."""

    kind: BackupKind
    """How it was made."""

    kind_name: str
    """What Odoo.sh calls that kind, such as `daily`."""

    taken_at: datetime
    """When it was taken, in UTC, to the second. It is what names the backup to Odoo.sh."""

    build_name: str
    """The name of the build it was taken from."""

    branch_name: str
    """The git branch of that build."""

    commit_hash: str
    """The full hash of that build's commit."""

    downloadable: bool
    """Whether Odoo.sh lets it be downloaded."""

    size: int | None
    """The bytes of its compressed SQL, or `None` when Odoo.sh gives none, as for all but `REMOTE`."""


@dataclass(frozen=True, slots=True)
class BackupRequest:
    """A manual backup asked of Odoo.sh, which lists it about a minute later."""

    build: Build
    """The build it is taken from: its branch's latest when it was asked for."""

    previous: datetime | None
    """When the newest manual backup of that build listed before the request was taken, which a wait looks past."""


@dataclass(frozen=True, slots=True)
class PreparedDownload:
    """A backup's file that Odoo.sh was asked to prepare, which it keeps for 2 hours once ready."""

    backup: Backup
    """The backup the file is made from."""

    build: Build
    """The build the backup was taken from, which the file is asked of."""

    worker_url: str
    """The address of the worker that holds the build, where the file is."""

    neutralized: bool
    """Whether the database is neutralized, as the page's dialog offers, rather than exact."""

    filestore: bool
    """Whether the file holds the filestore as well as the database."""

    link: str
    """The page's link to the file. It opens only in a browser signed in to Odoo.sh."""

    previous: int
    """The number of the project's newest notification before the request, which a wait looks past."""


@dataclass(frozen=True, slots=True)
class BackupFile:
    """A prepared backup's file as it arrives: a zip of the database's SQL, and of its filestore when asked."""

    size: int | None
    """Its bytes, or `None` when Odoo.sh does not say."""

    chunks: Iterator[bytes]
    """Its bytes as they arrive. Raises `UpstreamUnavailableError` when the connection drops early."""


class SessionSource(StrEnum):
    """Where a session came from."""

    ARGUMENT = "argument"
    """The caller passed it."""
    ENVIRONMENT = "environment"
    KEYRING = "keyring"


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """What is known of a session without asking Odoo.sh. It never holds the session."""

    source: SessionSource
    """Where the session came from."""

    stored_at: datetime | None
    """When the login stored it, in UTC, or `None` when it is not the stored one."""

    expires_at: datetime | None
    """When it passes the client-side max age, in UTC, or `None` when it is not the stored one."""


@dataclass(frozen=True, slots=True)
class Identity:
    """The user a session belongs to, as Odoo.sh reports them."""

    user_id: int
    """The number Odoo.sh gives the user."""

    name: str | None
    """The user's display name, when Odoo.sh gives one."""

    username: str
    """The user's GitHub login."""

    email: str | None
    """The user's email address, when Odoo.sh gives one. It is personal data, carried as given."""

    session: SessionInfo
    """The session that was asked with."""


@dataclass(frozen=True, slots=True)
class LogoutResult:
    """What a logout did."""

    source: SessionSource | None
    """Where the session came from, or `None` when there was none to log out of."""

    deleted: bool
    """Whether the stored session was deleted. One passed or set in the environment never is."""

    invalidated: bool
    """Whether Odoo.sh has ended the session, so that a copy of it no longer works."""

    failure: OdoucheError | None
    """Why Odoo.sh could not be asked to end the session, or `None`."""
