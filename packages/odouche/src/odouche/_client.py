"""The client: the one object a caller asks Odoo.sh through."""

import ipaddress
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager
from typing import Self

from odouche._session import SessionStore
from odouche._upstream import (
    allow_ip,
    audit,
    backups,
    branches,
    builds,
    history,
    logs,
    mails,
    members,
    overview,
    panels,
    project_settings,
    projects,
    rebuild,
    revision,
    settings,
    ssh,
    user,
    watch,
)
from odouche._upstream.transport import Transport
from odouche.models import (
    AuditEntry,
    Backup,
    BackupFile,
    BackupRequest,
    Branch,
    BranchSettings,
    Build,
    BuildRevision,
    Identity,
    Log,
    LogKind,
    LogLine,
    Mail,
    MailContent,
    Panel,
    PreparedDownload,
    Project,
    ProjectMember,
    ProjectOverview,
    ProjectSettings,
    ProjectSettingsChange,
    SessionInfo,
    SettingsChange,
    SettingsOutcome,
    SshTarget,
    Stage,
    Tracking,
)
from odouche.secret import Secret


# What the tests replace: the connection to Odoo.sh.
_transport: Callable[..., Transport] = Transport


class Client:
    """Asks Odoo.sh on behalf of one session.

    With no argument the session is the one in the environment, then the one stored by `login`.
    A tool that keeps sessions itself passes its own, which is never stored. Raises
    `NoSessionError` when there is none, `SessionExpiredError` when the stored one has passed its
    max age and `KeyringUnavailableError` when the keyring cannot be read.

    Every call raises `SessionExpiredError` when Odoo.sh rejects the session, after deleting it if
    it is the stored one. Nothing is cached: each call asks Odoo.sh. Use the client as a context
    manager, or call `close`.

    With `read_only`, a call that changes state on Odoo.sh raises `ReadOnlyError` and sends nothing.
    """

    def __init__(self, session: Secret | None = None, *, read_only: bool = False) -> None:
        store = SessionStore(session)
        resolved = store.load()
        self._session = SessionInfo(resolved.source, resolved.stored_at, resolved.expires_at)
        self._transport = _transport(resolved.session, on_rejected=store.discard, read_only=read_only)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the connections."""
        self._transport.close()

    @property
    def session(self) -> SessionInfo:
        """Where the session came from and when it passes its max age. Odoo.sh is not asked."""
        return self._session

    @property
    def read_only(self) -> bool:
        """Whether the client refuses the calls that change state on Odoo.sh."""
        return self._transport.read_only

    def identity(self) -> Identity:
        """Return the user the session belongs to, which also tells that Odoo.sh still accepts it."""
        return user.identity(self._transport, self._session)

    def projects(self) -> list[Project]:
        """List the projects the session's user can reach."""
        return projects.projects(self._transport)

    def project_overview(self, project: Project | str) -> ProjectOverview:
        """Return a project's overview, given as a `Project` or by its name.

        Its subscription, Odoo version, production build and branches by stage come from the
        requests its page sends, for its info and its branches, and its region from the projects.
        Its storage, workers and staging branches come from its settings, a fourth request, sent
        only when the session's user is an admin of the project, as the page shows them to an
        admin only: otherwise `hosting` is `None`. Only reads. Every token and code in the answers
        is dropped unread. Raises `NotFoundError` when the project is not one the session's user
        can reach, and `PermissionDeniedError` when Odoo.sh refuses its branches or its settings.
        """
        return overview.overview(self._transport, _project_name(project))

    def project_settings(self, project: Project | str) -> ProjectSettings:
        """Return a project's settings, as its Settings page shows them, given as a `Project` or by its name.

        Asks Odoo.sh twice, for the project's info then its settings, and only reads. Odoo.sh shows
        the settings to a project's admins only: anyone else gets `PermissionDeniedError` before
        the second request. A setting whose value the library does not know, or an allowed entry
        that is neither an address nor a network, raises `UpstreamChangedError` naming the field.
        Every token and code in the answers, and a submodule URL's credentials, are dropped unread. Raises
        `NotFoundError` when the project is not one the session's user can reach.
        """
        return project_settings.project_settings(self._transport, _project_name(project))

    def change_project_settings(
        self, project: Project | str, change: ProjectSettingsChange
    ) -> SettingsOutcome[ProjectSettings]:
        """Change state on Odoo.sh: set the settings `change` gives on a project, and return its settings before and after.

        Only those that differ are sent, in one request: the others keep their value. The allow
        list is sent whole, as the page sends it: each entry kept as written, those removed left
        out, the addresses added at the end. A setting the page disables, hides or refuses, given
        the settings after the change, raises `SettingsConflictError` before the request.

        Sent once. Raises `OutcomeUnknownError` when Odoo.sh did not confirm it, or the settings read
        back do not show it, `ReadOnlyError` on a read-only client, and `PermissionDeniedError` for
        a user who is not an admin of the project, before any change. Another setting Odoo.sh
        moved along is in the outcome's `moved`. Asks Odoo.sh four times, twice when nothing differs.
        """
        return project_settings.change_settings(self._transport, _project_name(project), change)

    def check_project_settings_change(
        self, current: ProjectSettings, change: ProjectSettingsChange
    ) -> ProjectSettingsChange | None:
        """Return the part of `change` that differs from `current`, or `None`, and raise as `change_project_settings` would.

        `current` is the project's settings, as `project_settings` reads them. A timeout's unit and
        bounds are not part of them: `change_project_settings` checks those. Odoo.sh is not asked
        and nothing changes, on a read-only client too: call it before asking the user.
        """
        return project_settings.narrow(current, change)

    def audit_log(
        self, project: Project | str, *, limit: int = audit.DEFAULT_LIMIT, timeout: float
    ) -> Generator[AuditEntry]:
        """Yield the entries of a project's audit log, given as a `Project` or by its name, newest first.

        At most `limit` entries are yielded. Odoo.sh has no paging: one request answers the last 30
        days whole, sent at the first read, and an answer over 16 MiB raises `OdoucheError` unread.
        Odoo.sh shows the log to a project's admins only: anyone else gets `PermissionDeniedError`
        before it is asked. An action the library does not know is `AuditKind.UNKNOWN`. Only reads.
        Raises `StreamTimeoutError` when the requests are not answered within `timeout` seconds,
        and `NotFoundError` when the project is not one the session's user can reach.
        """
        return audit.audit_log(self._transport, _project_name(project), limit=limit, timeout=timeout)

    def members(self, project: Project | str) -> list[ProjectMember]:
        """List the members of a project, given as a `Project` or by its name, with the role of each.

        They come in the order Odoo.sh answers them. Asks Odoo.sh twice, for the project's info then
        its settings, and only reads. Odoo.sh lists the members to a project's admins only: anyone
        else gets `PermissionDeniedError` before the second request. A role the library does not
        know raises `UpstreamChangedError` naming the field. Every token and code in the answers is
        dropped unread. Raises `NotFoundError` when the project is not one the session's user can reach.
        """
        return members.members(self._transport, _project_name(project))

    def branches(self, project: Project | str) -> list[Branch]:
        """List the branches of a project, given as a `Project` or by its name.

        They come in the order Odoo.sh answers them, which is not by name or by stage. Raises
        `NotFoundError` when the project is not among those the session's user can reach, whether
        or not it exists, and `PermissionDeniedError` when Odoo.sh lists it but refuses its
        branches. Asks Odoo.sh twice, for the projects and then for the branches.
        """
        return branches.branches(self._transport, _project_name(project))

    def backups(self, project: Project | str) -> list[Backup]:
        """List the backups of a project, given as a `Project` or by its name, newest first.

        They are every branch's: Odoo.sh answers a project's backups at once. A backup is named by
        its `taken_at`, which a `REMOTE` backup shares with the `DAILY` one it is a copy of. Raises
        `NotFoundError` when the project is not among those the session's user can reach. Asks
        Odoo.sh twice, for the projects and then for the backups.
        """
        return backups.backups(self._transport, _project_name(project))

    def create_backup(self, project: Project | str, branch: Branch | int, *, comment: str = "") -> BackupRequest:
        """Change state on Odoo.sh: ask for a manual backup of a branch's latest build.

        The project is given as a `Project` or by its name, the branch as a `Branch` or by its
        number. Odoo.sh answers nothing about the backup: it is listed by `backups` about a minute
        later, and `wait_for_backup` waits for it. Odoo.sh keeps a manual backup for three days.
        Only a staging or a production branch is backed up: any other raises `StageRefusedError`
        before the request.

        The request is sent once. Raises `OutcomeUnknownError` when it left and Odoo.sh did not
        confirm it: look at the backups before calling again. Raises `ReadOnlyError` on a
        read-only client, and `NotFoundError` when the branch has no build or is not the project's.
        """
        stage = branch.stage if isinstance(branch, Branch) else None
        return backups.backup(self._transport, _project_name(project), _branch_id(branch), stage, comment)

    def check_backup(self, branch: Branch) -> None:
        """Raise `StageRefusedError` when `create_backup` would refuse the branch for its stage.

        Odoo.sh is not asked and nothing changes, on a read-only client too.
        """
        backups.allow(branch.stage)

    def wait_for_backup(
        self, project: Project | str, request: BackupRequest, *, timeout: float
    ) -> Generator[Backup | None]:
        """Yield the backup `create_backup` asked for once Odoo.sh has finished it, and end.

        Odoo.sh is asked for the project's backups every five seconds, then whether it is still
        making it, and `None` is yielded after each look that does not find it finished, so a
        caller can stop the wait between two. Odoo.sh lists a backup before it is finished, and
        refuses a file of it until then. Raises `StreamTimeoutError` after `timeout` seconds.
        """
        return backups.wait(self._transport, _project_name(project), request, timeout=timeout)

    def prepare_download(
        self, project: Project | str, backup: Backup, *, neutralized: bool = True, filestore: bool = True
    ) -> PreparedDownload:
        """Change state on Odoo.sh: ask it to prepare the file of a backup of a project.

        The database is neutralized unless `neutralized` is false, which asks for the exact one,
        and the file holds the filestore unless `filestore` is false. Only the first combination
        has been seen. `wait_for_download` waits until the file is ready, and Odoo.sh keeps it for
        2 hours from then.

        The request is sent once, on the build the backup was taken from. Raises `ValueError` for
        a backup that is not `downloadable`, `NotFoundError` when that build is no longer among
        its branch's latest, `OutcomeUnknownError` when the request left and Odoo.sh did not
        confirm it, and `ReadOnlyError` on a read-only client.
        """
        return backups.prepare(
            self._transport, _project_name(project), backup, neutralized=neutralized, filestore=filestore
        )

    def find_download(
        self, project: Project | str, backup: Backup, *, neutralized: bool = True, filestore: bool = True
    ) -> PreparedDownload | None:
        """Return the file of a backup that Odoo.sh already holds, prepared with these choices, or `None`.

        It only reads, on a read-only client too. A notification of Odoo.sh names the file, and
        the file is then opened once and closed, to tell it is still there. `download` takes what
        it returns, with no wait. Raises as `prepare_download` does before its request.
        """
        return backups.find(
            self._transport, _project_name(project), backup, neutralized=neutralized, filestore=filestore
        )

    def wait_for_download(
        self, project: Project | str, prepared: PreparedDownload, *, timeout: float
    ) -> Generator[None]:
        """Yield `None` until the file `prepare_download` asked for is ready, and end once it is.

        Odoo.sh is asked for the project's notifications every five seconds, and the file is ready
        when one links to it. Raises `StreamTimeoutError` after `timeout` seconds.
        """
        return backups.wait_download(self._transport, _project_name(project), prepared, timeout=timeout)

    def download(self, prepared: PreparedDownload) -> AbstractContextManager[BackupFile]:
        """Open a prepared backup's file, to be read as it arrives. Leaving the context closes the connection.

        The file is asked of its build's worker with a token Odoo.sh hands over for it, which is
        sent nowhere else and kept nowhere. Raises `NotFoundError` when the file is not ready or
        Odoo.sh no longer keeps it, and `UpstreamUnavailableError` from `chunks` when the
        connection drops before its last byte.
        """
        return backups.download(self._transport, prepared)

    def builds(self, branch: Branch | int, *, limit: int = builds.DEFAULT_LIMIT) -> list[Build]:
        """List the latest builds of a branch, given as a `Branch` or by its number, newest first.

        At most `limit` builds are returned, in one request. Odoo.sh may answer fewer than asked
        for: it has only been seen to answer up to four, and older builds are out of reach. Raises
        `NotFoundError` when the branch is not one the session's user can reach.
        """
        return builds.builds(self._transport, _branch_id(branch), limit)

    def build(self, branch: Branch | int, build_id: int) -> Build:
        """Return one build of a branch by its number.

        Odoo.sh has no request for a build by its number, so the build is looked for among the
        branch's latest. Raises `NotFoundError` when it is not there, which an older build is not.

        Odoo.sh has no settings request for a build either: the builds answer gives only each
        build's operating system and Odoo version, and a new build takes its branch's settings,
        which `branch_settings` reads.
        """
        return builds.build(self._transport, _branch_id(branch), build_id)

    def latest_build(self, branch: Branch | int) -> Build | None:
        """Return the newest build of a branch, or `None` when it has none."""
        latest = builds.builds(self._transport, _branch_id(branch), 1)
        return latest[0] if latest else None

    def history(self, branch: Branch | int, *, limit: int = history.PAGE, timeout: float) -> Generator[Tracking]:
        """Yield the events of a branch, given as a `Branch` or by its number, newest first.

        At most `limit` events are yielded. Odoo.sh answers them twenty at a time, and the next
        twenty are asked for only when the iterator is read past the last ones. That the next page
        is at an offset of twenty is inferred, not seen. An event read again, because a newer one
        pushed it down, is skipped, and a page with nothing older raises `UpstreamChangedError`. Raises `StreamTimeoutError` when a page is still to be
        asked for after `timeout` seconds, and `NotFoundError` when the branch is not one the
        session's user can reach.
        """
        return history.history(self._transport, _branch_id(branch), limit=limit, timeout=timeout)

    def branch_settings(self, branch: Branch | int) -> BranchSettings:
        """Return a branch's settings, given as a `Branch` or by its number.

        A setting whose value the library does not know raises `UpstreamChangedError` naming it,
        rather than passing through unchecked. Raises `NotFoundError` when the branch is not one
        the session's user can reach. Asks Odoo.sh once, and only reads.
        """
        return settings.settings(self._transport, _branch_id(branch))

    def change_branch_settings(self, branch: Branch | int, change: SettingsChange) -> SettingsOutcome[BranchSettings]:
        """Change state on Odoo.sh: set the settings `change` gives on a branch, and return its settings before and after.

        Only those that differ are sent, in one request, as the page sends a section of its Settings
        tab: the others keep their value. The branch's stage is read again, and a setting the tab
        does not show in it raises `StageRefusedError` before the request; one it disables or hides,
        given the settings after the change, raises `SettingsConflictError`.

        Sent once. Raises `OutcomeUnknownError` when Odoo.sh did not confirm it, or the settings read
        back do not show it, `ReadOnlyError` on a read-only client, `PermissionDeniedError` when
        refused, and `NotFoundError` for a branch out of reach. Another setting Odoo.sh moved along
        is in the outcome's `moved`. Asks Odoo.sh four times, twice when nothing differs.
        """
        return settings.change_settings(self._transport, _branch_id(branch), change)

    def check_settings_change(
        self, branch: Branch, current: BranchSettings, change: SettingsChange
    ) -> SettingsChange | None:
        """Return the part of `change` that differs from `current`, or `None`, and raise as `change_branch_settings` would.

        `current` is the branch's settings, as `branch_settings` reads them. Odoo.sh is not asked
        and nothing changes, on a read-only client too: call it before asking the user.
        """
        return settings.narrow(branch.stage, current, change)

    def move_branch(self, branch: Branch | int, to: Stage) -> Branch:
        """Change state on Odoo.sh: move a branch between development and staging, and return it in its new stage.

        A move to staging starts a build of the branch on a copy of production's data; a move to
        development drops its staging builds, which are not backed up. A production branch, a move
        to production, a stage the library does not know and a branch already in `to` raise
        `StageRefusedError` before the request. The stage that decides is read again first.

        Sent once. Raises `OutcomeUnknownError` when Odoo.sh did not confirm it or the branch read
        back is not in `to`, `ReadOnlyError` on a read-only client, `PermissionDeniedError` when
        refused, and `NotFoundError` for a branch out of reach. Asks Odoo.sh three times. A branch
        that is not a number raises `TypeError`.
        """
        held = branch.stage if isinstance(branch, Branch) else None
        return branches.move(self._transport, _branch_id(branch), to, held)

    def check_move(self, branch: Branch, to: Stage) -> None:
        """Raise `StageRefusedError` when `move_branch` would refuse the move for the branch's stage or `to`.

        Odoo.sh is not asked and nothing changes, on a read-only client too.
        """
        branches.allow_move(branch.id, branch.stage, Stage(to))

    def build_revision(self, project: Project | str, build: Build) -> BuildRevision:
        """Return the revision a build of a project runs: its head commit, its Odoo version, and its branch's selected Odoo revision.

        Odoo.sh ties no Odoo revision to a build, so the branch's is the one it has selected now,
        which the build may not run. Odoo.sh gives no commit for a submodule. Asks Odoo.sh twice,
        and a third time for the project's Odoo version when the branch has none of its own, and
        only reads. Raises `NotFoundError` when the build is no longer among its branch's latest
        or the project is not one the session's user can reach, and `UpstreamChangedError`
        naming a field that is not as seen.
        """
        return revision.revision(self._transport, _project_name(project), build)

    def ssh_target(self, build: Build) -> SshTarget:
        """Return the user and the host `ssh` reaches a build with. Odoo.sh is not asked.

        Odoo.sh accepts there the keys registered on the user's account, not the session. Raises
        `NotFoundError` when the build has no host, and `UpstreamChangedError` when its number or
        its address is not one that can be handed to `ssh` as it is.
        """
        return ssh.target(build)

    def panel_url(self, project: Project | str, branch: Branch, build: Build, panel: Panel | str) -> str:
        """Return the address of a panel of a build of a branch, for a browser to open. Odoo.sh is not asked.

        The shell and the editor are on the build's own host, the monitor is the branch's on
        `www.odoo.sh`. None carries a token or the session: the browser signs in to Odoo.sh on its
        own. As on the page, a build has panels once it is `DONE`, judged from `build` as given,
        and only a staging or a production branch has a monitor, which shows its latest build.
        Raises `NotFoundError` for a build that is not done, one waiting for a worker included, or
        a monitor of another stage, `ValueError` for an unknown panel or a build of another branch,
        and `UpstreamChangedError` when the build's address is not a bare host under `odoo.com`.
        """
        return panels.url(_project_name(project), branch, build, Panel(panel))

    def allow_ip(self, branch: Branch | int) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
        """Change state on Odoo.sh: let the address this machine reaches it from connect with `ssh`.

        Returns the address, which Odoo.sh takes from the connection: behind a proxy it is the
        proxy's. Odoo.sh says the rule lasts one hour and takes up to five minutes to apply. The
        branch is given as a `Branch` or by its number.

        The request is sent once. Raises `OutcomeUnknownError` when it left and Odoo.sh did not
        confirm it, `ReadOnlyError` on a read-only client, and `PermissionDeniedError` when Odoo.sh
        refuses it to the session's user, as the page expects for a stage above their access.
        """
        return allow_ip.allow_ip(self._transport, _branch_id(branch))

    def rebuild(self, branch: Branch | int) -> Build:
        """Change state on Odoo.sh: start a new build of a branch, given as a `Branch` or by its number.

        Returns the new build, which replaces the branch's latest one. Only a development or a
        staging branch is rebuilt: any other raises `StageRefusedError` before the request.

        The request is sent once. Raises `OutcomeUnknownError` when it left and Odoo.sh did not
        confirm it, or the new build cannot be found: look at the branch before calling again,
        since a second call can start a second build. Raises `ReadOnlyError` on a read-only
        client, and `NotFoundError` when the branch is not one the session's user can reach.
        A branch that is not a number raises `TypeError`.
        """
        stage = branch.stage if isinstance(branch, Branch) else None
        return rebuild.rebuild(self._transport, _branch_id(branch), stage)

    def check_rebuild(self, branch: Branch) -> None:
        """Raise `StageRefusedError` when `rebuild` would refuse the branch for its stage.

        Odoo.sh is not asked and nothing changes, on a read-only client too.
        """
        rebuild.allow(branch.stage)

    def watch_build(
        self, project: Project | str, build: Build, *, timeout: float, pulse: float | None = None
    ) -> Generator[Build]:
        """Yield a build of a project as it is now, then at each change, and end once it has finished.

        A change is one of `status`, `result` or `status_info`. The last build yielded is the
        finished one, and a build that has already finished is yielded once. The watch stays on
        this build: a newer one on the branch ends it as `DROPPED`. Closing the iterator closes the
        connection.

        With `pulse`, the build is also yielded unchanged, every `pulse` seconds at least while
        nothing changes. An iterator is closed only between two builds, so a caller that may have
        to stop the watch asks for one.

        Raises `StreamTimeoutError` after `timeout` seconds, `UpstreamUnavailableError` when the
        connection fails three times in a row or Odoo.sh cannot be asked for the build, and
        `NotFoundError` when the build is not among its
        branch's latest, or the project is not one the session's user can reach.
        """
        return watch.watch(self._transport, project, build, timeout=timeout, pulse=pulse)

    def logs(self, project: Project | str, build: Build) -> list[Log]:
        """List the logs a build of a project has, which is none while it waits for a worker.

        Raises `NotFoundError` when the build is not among its branch's latest, or the project is
        not one the session's user can reach.
        """
        return logs.logs(self._transport, _project_name(project), build)

    def read_log(
        self, project: Project | str, build: Build, kind: LogKind | str, *, tail: int | None = None
    ) -> Generator[LogLine]:
        """Yield the lines of one log of a build, given as a `LogKind` or by its name.

        Log content is untrusted: it is whatever a process printed, terminal escape sequences and
        secrets of the instance included, and it is returned unchanged.

        With `tail`, only the last lines are yielded, out of the log's last mebibyte. A line
        longer than 64 KiB is cut. Closing the iterator closes the connection. Raises
        `NotFoundError` when the build has no such log.
        """
        return logs.read(self._transport, _project_name(project), build, kind, tail)

    def follow_log(
        self,
        project: Project | str,
        build: Build,
        kind: LogKind | str,
        *,
        timeout: float,
        tail: int = 0,
        offset: int | None = None,
    ) -> Generator[LogLine]:
        """Yield the lines of one log of a build as they are written, until the iterator is closed.

        Log content is untrusted, as in `read_log`.

        It starts after the log's last `tail` lines, or at `offset`, which is the `offset` of a
        line read before. Odoo.sh is asked every second. Raises `StreamTimeoutError` after
        `timeout` seconds, which `math.inf` makes no limit, `UpstreamUnavailableError` when a
        failed request is not answered after two more tries, and `NotFoundError` when the build
        has no such log.
        """
        return logs.follow(
            self._transport, _project_name(project), build, kind, timeout=timeout, tail=tail, offset=offset
        )

    def mails(
        self, project: Project | str, branch: Branch, build: Build, *, limit: int = mails.DEFAULT_LIMIT
    ) -> list[Mail]:
        """List the mails a build of a development or a staging branch caught instead of sending, newest first.

        At most `limit` mails, out of the latest 1000 the worker keeps. They are asked of the
        build's worker with the project's token, never with the session, and none while the build
        waits for a worker. A mail's fields are untrusted: the build's code or its data wrote them.
        Raises `NotFoundError` for a branch of another stage, before any request, or a build not
        among its branch's latest, `ValueError` for a build of another branch, and `OdoucheError`
        when the worker's list is over 16 MiB, which is not read.
        """
        return mails.mails(self._transport, _project_name(project), branch, build, limit)

    def mail(self, project: Project | str, branch: Branch, build: Build, mail_id: str) -> MailContent:
        """Return one mail a build caught, by the `id` that `mails` gives it, with its text and its attachments' names.

        Its content is untrusted and never rendered: an HTML body is turned into text, and nothing
        in it is followed. A body is cut at 1 MiB as UTF-8, a header at 65536 characters and the
        parts at 1000, every MIME part counted, containers included. A mail over 16 MiB is not
        read. Each is `truncated`. Raises `NotFoundError` for a mail the build did not catch, and
        as `mails` does, and `OdoucheError` when the worker's list is over 16 MiB.
        """
        return mails.mail(self._transport, _project_name(project), branch, build, mail_id)


def _project_name(project: Project | str) -> str:
    return project.name if isinstance(project, Project) else project


def _branch_id(branch: Branch | int) -> int:
    return branch.id if isinstance(branch, Branch) else branch
