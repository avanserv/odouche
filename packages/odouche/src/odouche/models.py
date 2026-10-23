"""What the library returns: its own models, not the payloads of Odoo.sh."""

from collections.abc import Iterator
from dataclasses import dataclass
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
    """The build an event of a branch's history made, as it is now. `Client.build` has the rest of it."""

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


@dataclass(frozen=True, slots=True)
class SshTarget:
    """Where `ssh` reaches a build: the user to log in as and the host."""

    user: str
    """The user on the build's host, which is the build's number."""

    host: str
    """The build's own host."""


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
