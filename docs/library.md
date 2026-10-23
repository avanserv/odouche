# Library

`odouche` is the Python client for Odoo.sh that the command-line tool and the MCP server are built
on. It is meant to be used directly in your own tools as well.

```bash
uv add odouche
```

## What it is designed to be

- **Typed.** The library returns typed models rather than raw Odoo.sh payloads, and ships type
  information (`py.typed`).
- **The only layer that knows Odoo.sh.** Endpoints, payload shapes and anything scraped from the
  web interface live in one place, so an upstream change is fixed in one place.
- **Synchronous.** Every call is a plain function. From async code, run it in a thread, for
  example with `asyncio.to_thread`.
- **Streaming where it matters.** Watching a build and following logs return iterators of typed
  events. Close the iterator to stop; pass a deadline to bound it.

## Session

The session is taken from the `ODOUCHE_SESSION` environment variable when it is set, and from the
OS keyring otherwise. [Security](security.md) says where it is stored and for how long.

For headless use, such as CI, set `ODOUCHE_SESSION` to the `session_id` cookie of `www.odoo.sh`
from the job's secrets. The keyring is then neither read nor written, and nothing below changes.

## Logging in

`login` opens a browser for the user to sign in to Odoo.sh with GitHub, then stores the session in
the keyring, replacing the one stored before.

```python
import getpass

import odouche


def ask() -> odouche.Secret:
    return odouche.Secret(getpass.getpass("session_id cookie of www.odoo.sh: "))


odouche.login(ask=ask, notify=lambda step: print(step.value), timeout=300)
```

- The library neither prints nor prompts. `notify` is called with a `LoginStep`: `KEYRING` when
  the keyring is checked and may be showing a dialog to be unlocked, `BROWSER` when the window is
  open, `PASTE` when no browser can be launched and `ask` is about to be called.
- `ask` returns the pasted cookie, wrapped in a `Secret`. Without it, a machine with no browser to
  launch gets a `LoginError`.
- The session is stored once Odoo.sh has answered one request sent with it. A login that is
  refused or times out leaves the stored session as it was.
- A login nobody completes raises `LoginTimeoutError` after `timeout` seconds.
- Called from the main thread, a login that `SIGTERM` or `SIGHUP` ends deletes the browser profile
  before the signal takes effect.
- With no keyring to store the session in, or one not unlocked within `timeout` seconds,
  `KeyringUnavailableError` is raised before the browser opens.
- Outside a login, a keyring showing a dialog is waited for ten seconds, then
  `KeyringUnavailableError` is raised.

## Logging out

`logout` ends the stored session on Odoo.sh, so that a copy of it stops working, and deletes it
from the keyring.

```python
import odouche


result = odouche.logout()
if result.failure is not None:
    print("Deleted here, but Odoo.sh could not be asked to end it:", result.failure)
```

It returns a `LogoutResult`:

| Field | Meaning |
| --- | --- |
| `source` | A `SessionSource`: `KEYRING`, `ENVIRONMENT` or `ARGUMENT`. `None` when there was no session. |
| `deleted` | Whether the stored session was deleted. |
| `invalidated` | Whether Odoo.sh has ended the session. |
| `failure` | The error that kept Odoo.sh from being asked, or `None`. |

- The stored session is deleted even when Odoo.sh cannot be reached. `failure` then holds the
  error, and the session works until Odoo.sh expires it.
- With no session, nothing is asked and nothing is raised. A stored one past its max age, or
  that cannot be read, is deleted and not ended on Odoo.sh.
- A session from the environment or passed as `logout(session)` is not deleted: unset it
  yourself. It is ended on Odoo.sh only with `invalidate_given=True`, since a session shared
  between jobs would stop working for all of them. The stored session is then left as it is:
  unset the variable and call `logout()` again to end it.
- A session passed or set in the environment that is not a `session_id` cookie value raises
  `NoSessionError`.
- `KeyringUnavailableError` is raised when the keyring cannot be read or the session not deleted.
  When it is not deleted, the message says whether Odoo.sh ended it.

## Client

`Client` is the one object everything is asked through. It closes its connections when the block
ends.

```python
import odouche


with odouche.Client() as client:
    for project in client.projects():
        print(project.name, project.repository, project.url)
```

- With no argument, the session is resolved as [above](#session). A tool that keeps sessions itself
  passes its own, `odouche.Client(odouche.Secret(value))`, which is never stored.
- With no session, or a value that is not a `session_id` cookie value, `Client()` raises
  `NoSessionError`.
- Nothing is cached: each call asks Odoo.sh.

### Who is logged in

`client.identity()` asks Odoo.sh who the session belongs to, and returns an `Identity`. Being
answered also means the session is still valid: a rejected one raises `SessionExpiredError`.

| Field | Meaning |
| --- | --- |
| `user_id` | The number Odoo.sh gives the user. |
| `name` | The user's display name, or `None`. |
| `username` | The user's GitHub login. |
| `email` | The user's email address, or `None`. Treat it as personal data. |
| `session` | The `SessionInfo` below. |

`client.session` is a `SessionInfo`, read without asking Odoo.sh, so it works offline. It never
holds the session itself.

| Field | Meaning |
| --- | --- |
| `source` | A `SessionSource`: `KEYRING`, `ENVIRONMENT` or `ARGUMENT`. |
| `stored_at` | When the login stored the session. `None` unless it came from the keyring. |
| `expires_at` | When it passes the client-side max age. `None` unless it came from the keyring. |

### Projects

`client.projects()` returns the projects the session's user can reach, as a list of `Project`:

| Field | Meaning |
| --- | --- |
| `id` | The number Odoo.sh gives the project. |
| `name` | The project's name on Odoo.sh, as in the address of its page. |
| `repository` | The GitHub repository the project builds, as `owner/name`. |
| `url` | The address of the project's page on Odoo.sh. |

### Branches

`client.branches(project)` returns the branches of a project, as a list of `Branch`. `project` is a
`Project` or a project's name.

| Field | Meaning |
| --- | --- |
| `id` | The number Odoo.sh gives the branch. |
| `name` | The git branch. |
| `stage` | A `Stage`: `PRODUCTION`, `STAGING`, `DEVELOPMENT` or `UNKNOWN`. |
| `stage_name` | What Odoo.sh calls that stage, such as `dev`. |

- The branches come in the order Odoo.sh answers them, which is not by name or by stage.
- A stage the library does not know is `Stage.UNKNOWN`, not an error. `stage_name` says which.
- A project that is not among those the user can reach raises `NotFoundError`, whether or not it
  exists. One that Odoo.sh lists but refuses the branches of raises `PermissionDeniedError`.
- Each call asks Odoo.sh twice: for the projects, then for the branches.

### Backups

`client.backups(project)` returns the backups of a project, every branch's, newest first, as a list
of `Backup`. `project` is a `Project` or a project's name.

```python
import odouche


with odouche.Client() as client:
    for backup in client.backups("acme-shop"):
        print(backup.taken_at, backup.kind, backup.branch_name, backup.downloadable)
```

| Field | Meaning |
| --- | --- |
| `kind` | A `BackupKind`: `MANUAL`, `DAILY`, `REMOTE` or `UNKNOWN`. |
| `kind_name` | What Odoo.sh calls that kind. |
| `taken_at` | When it was taken, in UTC, to the second. It is what names the backup. |
| `build_name` | The name of the build it was taken from. |
| `branch_name`, `commit_hash` | The git branch and the full commit of that build. |
| `downloadable` | Whether Odoo.sh lets it be downloaded. |
| `size` | The bytes of its compressed SQL, or `None`: only a `REMOTE` backup has one. |

- A `REMOTE` backup is a daily one kept off-site, under the same `taken_at` as the `DAILY` one
  while that is kept. Odoo.sh does not let it be downloaded as it is.
- A backup has no number: the one Odoo.sh gives a `REMOTE` backup changes between two answers.
- A project that is not among those the user can reach raises `NotFoundError`, whether or not it
  exists. Each call asks Odoo.sh twice: for the projects, then for the backups.

### Builds

`client.builds(branch)` returns the latest builds of a branch, newest first, as a list of `Build`.
`branch` is a `Branch` or a branch's number.

```python
import odouche


with odouche.Client() as client:
    branches = {branch.name: branch for branch in client.branches("acme-shop")}
    branch = branches["feature-invoicing"]
    for build in client.builds(branch, limit=2):
        print(build.id, build.status, build.result, build.commit.hash)
    latest = client.latest_build(branch)
```

| Field | Meaning |
| --- | --- |
| `id` | The number Odoo.sh gives the build. |
| `name` | The build's name on Odoo.sh. |
| `branch_id`, `branch_name` | The branch the build belongs to. |
| `commit` | A `Commit`: `hash`, `message`, `author`, `timestamp` and `url`. |
| `status` | A `BuildStatus`: `PROGRESS`, `UPDATING`, `DONE`, `DROPPED`, `SKIPPED`, `KILLED` or `UNKNOWN`. |
| `status_name` | What Odoo.sh calls that status. |
| `result` | A `BuildResult`: `SUCCESS`, `FAILED`, `WARNING` or `UNKNOWN`. `None` when Odoo.sh gives none. |
| `result_name` | What Odoo.sh calls that result. `None` with `result`. |
| `status_info` | What the build is doing, in Odoo.sh's own words, or `None`. |
| `started_at` | When a worker took the build. `None` while it waits for one. |
| `url` | The address of the build's database, or `None`. |
| `finished` | Whether the build has ended, whatever its result. |

- `finished` is true for `DONE`, `DROPPED`, `SKIPPED` and `KILLED`. A `DROPPED` build is one a
  newer build replaced.
- A status or result the library does not know is `UNKNOWN`, not an error, and the `_name` field
  says which. An unknown status is not finished.
- Timestamps are timezone-aware, in UTC.
- `limit` defaults to 4 and each call is one request. Odoo.sh may return fewer builds than asked
  for: it has only been seen to return up to four, and older builds are out of reach. A `limit`
  under 1 raises `ValueError`, and a branch, build or limit that is not an integer `TypeError`.
- `client.latest_build(branch)` returns the newest build, or `None` for a branch with none.
- `client.build(branch, build_id)` returns one build. Odoo.sh has no request for a build by its
  number, so it is looked for among the branch's latest and raises `NotFoundError` when it is not
  there.
- A branch the user cannot reach raises `NotFoundError`. Odoo.sh gives no reason.
- A commit's `author` is another person's name. Treat it as personal data.

`client.watch_build(project, build, timeout=...)` yields the build as it is now, then again at
each change, and ends once it has finished. `project` is a `Project` or a project's name.

```python
import odouche


with odouche.Client() as client:
    branches = {branch.name: branch for branch in client.branches("acme-shop")}
    branch = branches["feature-invoicing"]
    build = client.latest_build(branch)
    if build is None:
        raise SystemExit("The branch has no build yet.")
    try:
        for build in client.watch_build("acme-shop", build, timeout=1800):
            print(build.status, build.status_info)
    except odouche.StreamTimeoutError:
        print("Still running after half an hour.")
    else:
        print(build.result)
```

- A change is one of `status`, `result` or `status_info`. The last build yielded is the finished
  one, and a build that has already finished is yielded once, with no wait.
- The watch stays on its build. A newer build on the branch ends it as `DROPPED`.
- With `pulse=2`, the build is also yielded unchanged, every 2 seconds at least while nothing
  changes, so a caller that watches in a thread can close the iterator.
- After `timeout` seconds it raises `StreamTimeoutError`: the build is still running, which is not
  Odoo.sh being unavailable. A request of the watch waits no longer than what is left of them.
- Changes come over a websocket to `www.odoo.sh`. Odoo.sh is also asked for the build at the
  start, when the connection is opened again and after a minute with no news of the build, which
  is what detects a rejected session.
- A connection that fails is opened again twice. Then `UpstreamUnavailableError` is raised.
- Closing the iterator closes the connection.
- A build that is no longer among its branch's latest raises `NotFoundError`.

### History

`client.history(branch, timeout=...)` yields the events of a branch, newest first, as `Tracking`:
each push with its commits, each rebuild and each move between stages. `branch` is a `Branch` or a
branch's number. It reaches builds older than `builds` does.

```python
import odouche


with odouche.Client() as client:
    branches = {branch.name: branch for branch in client.branches("acme-shop")}
    for event in client.history(branches["feature-invoicing"], limit=30, timeout=60):
        print(event.created_at, event.kind, event.build and event.build.id, len(event.commits))
```

| Field | Meaning |
| --- | --- |
| `id` | The number Odoo.sh gives the event. |
| `kind` | A `TrackingKind`: `PUSH`, `REBUILD`, `STAGE` or `UNKNOWN`. |
| `kind_name` | What Odoo.sh calls that kind. |
| `created_at` | When it happened, in UTC. |
| `build` | A `TrackedBuild`: `id`, `status`, `status_name`, `result` and `result_name`, or `None`. |
| `commits` | The `PushedCommit`s of a push, each with `hash`, `message` and `url`, and no author or date. |
| `pusher` | Who pushed, as Odoo.sh names them, or `None`. Treat it as personal data. |
| `source_stage`, `target_stage` | The `Stage`s of a move, or `None`. A branch's creation has a target only. |

- Odoo.sh answers twenty events a request. The next twenty are asked for only when the iterator is
  read past the last ones, and none once `limit` events, 20 by default, are yielded.
- That the next twenty are at an offset of twenty is inferred, not seen. An event read again,
  because a newer one pushed it down, is skipped. A page with nothing older raises
  `UpstreamChangedError` rather than looping.
- A page still to be asked for after `timeout` seconds raises `StreamTimeoutError`. A request
  waits no longer than what is left of them.
- The build is as it is now, with no commit, name or address: `client.build` has the rest of a
  build that is still among the branch's latest.

### Branch settings

`client.branch_settings(branch)` returns a branch's settings, as its Settings tab shows them, as
`BranchSettings`. `branch` is a `Branch` or a branch's number.

```python
import odouche


with odouche.Client() as client:
    branches = {branch.name: branch for branch in client.branches("acme-shop")}
    settings = client.branch_settings(branches["feature-invoicing"])
    print(settings.push_behavior, settings.machine)
```

| Field | Meaning |
| --- | --- |
| `push_behavior` | A `PushBehavior`, what a new commit does: `NOTHING`, `NEW_BUILD` or `UPDATE`. |
| `project_defaults` | Whether the project's development defaults apply instead of the six fields below. |
| `module_install` | A `ModuleInstall`, the modules a new build installs: `REPOSITORY`, `ALL` or `LISTED`. |
| `modules` | The modules stored for `LISTED`, whatever `module_install` is. They apply only to `LISTED`. |
| `tests` | A `BuildTests`, the tests a new build runs: `OFF`, `MODULES` (the installed modules') or `TAGS`. |
| `test_tags` | The Odoo test tags stored for `TAGS`, whatever `tests` is, or `None`. They apply only to `TAGS`. |
| `demo_data` | Whether a new build loads demonstration data. |
| `ai_agent` | An `AiAgent`, the agent the AI tab runs: `CLAUDE` or `OPENCODE`. |
| `odoo_version` | The Odoo version, such as `19.0`, or `None` for the project's. |
| `odoo_revision_id` | The id Odoo.sh gives the pinned weekly Odoo revision, or `None` for the latest. Its name is not given. |
| `machine`, `recommended_machine` | The operating system builds run on, and the one Odoo.sh recommends, such as `ubuntu-24.04`. |
| `next_machine` | The operating system the next commit's build moves to, or `None`. |
| `domains` | The custom domains. |
| `dns_target` | The host a custom domain's CNAME record points to. |

- It is one request, and only reads.
- A value the library does not know, in any of the four enumerations, raises
  `UpstreamChangedError` naming the field, unlike a `Stage` that becomes `UNKNOWN`: a setting is
  never passed through unchecked.
- The new build options, `project_defaults` to `ai_agent`, apply to a development branch only.
  While `project_defaults` is true the project's development defaults apply instead, and those are
  not read.
- Odoo.sh has no settings request for a build, as `Client.build` says.

### Build revision

`client.build_revision(project, build)` returns what a build of a project runs, as
`BuildRevision`: its head commit, its Odoo version, and the Odoo revision its branch has selected,
with the commit of each of Odoo's own repositories. `project` is a `Project` or a project's name.

```python
import odouche


with odouche.Client() as client:
    build = client.build(51044, 88212)
    revision = client.build_revision("acme-shop", build)
    print(revision.commit.hash)
    if revision.branch_odoo_revision is not None:
        for ref in revision.branch_odoo_revision.refs:
            print(ref.repository, ref.commit_hash)
```

| `BuildRevision` field | Meaning |
| --- | --- |
| `build_id`, `build_name`, `branch_name` | The build's number and name, and its git branch. |
| `commit` | The head commit of the project's repository, as a `Commit`, with its full hash. |
| `odoo_version` | The Odoo version the build was made with, such as `19.0`. |
| `branch_odoo_revision` | The `OdooRevision` the branch has selected now, or `None`. |

| `OdooRevision` field | Meaning |
| --- | --- |
| `id` | The number Odoo.sh gives the revision, as `BranchSettings.odoo_revision_id` holds it when pinned. |
| `version` | The Odoo version, such as `19.0`. |
| `pinned` | Whether the branch pins this revision. Otherwise it is the latest of its version, and moves on. |
| `refs` | An `OdooRef` for each repository, in the order Odoo.sh gives them. |

| `OdooRef` field | Meaning |
| --- | --- |
| `repository` | What Odoo.sh calls the repository, such as `enterprise`. |
| `commit_hash` | The commit's full hash. |
| `url` | The repository's address. |

- It is two requests, and only reads. A branch with no Odoo version of its own follows the
  project's, which is a third request.
- Odoo.sh ties no Odoo revision to a build: `branch_odoo_revision` is the one the branch has
  selected now, which the build may not run.
- `branch_odoo_revision` is `None` when Odoo.sh gives none.
- Odoo.sh gives no commit for a submodule of the project's repository, so nothing in the model
  says whether the repository has submodules.
- An answer not in the shape seen raises `UpstreamChangedError` naming the field.

### Logs

`client.logs(project, build)` returns the logs a build has, as a list of `Log`. `project` is a
`Project` or a project's name, and `build` a `Build`.

| Field | Meaning |
| --- | --- |
| `kind` | A `LogKind`: `INSTALL`, `PIP`, `ODOO`, `UPDATE`, `NEUTRALIZE`, `UPGRADE` or `UNKNOWN`. |
| `name` | What Odoo.sh calls the log. |
| `modified_at` | When it was last written to, in UTC. |
| `size` | Its size in Odoo.sh's own words, such as `156 KB`. |

`client.read_log(project, build, kind)` yields the lines of one log, and
`client.follow_log(project, build, kind, timeout=...)` the lines written from now on. `kind` is a
`LogKind` or a log's name.

```python
import odouche


with odouche.Client() as client:
    branches = {branch.name: branch for branch in client.branches("acme-shop")}
    branch = branches["feature-invoicing"]
    build = client.latest_build(branch)
    if build is None:
        raise SystemExit("The branch has no build yet.")
    for log in client.logs("acme-shop", build):
        print(log.name, log.size)
    for line in client.read_log("acme-shop", build, odouche.LogKind.INSTALL, tail=20):
        print(repr(line.text))
    try:
        for line in client.follow_log("acme-shop", build, odouche.LogKind.ODOO, timeout=600):
            print(repr(line.text))
    except odouche.StreamTimeoutError:
        print("Followed for ten minutes.")
```

Each line is a `LogLine`:

| Field | Meaning |
| --- | --- |
| `text` | The line without its newline. |
| `offset` | The byte just past the line. |
| `truncated` | Whether the line was cut. |

!!! warning "Log content is untrusted"

    A line is whatever a process printed, unchanged: it can hold terminal escape sequences and
    secrets of the instance. Neutralise it before showing it.

- A build has only some of the logs, and none while it waits for a worker. A log it does not have
  raises `NotFoundError`.
- `tail=N` yields the last N lines, out of the log's last mebibyte.
- Closing the iterator of a read closes the connection.
- A line longer than 64 KiB is cut to that and marked `truncated`. Bytes that are not UTF-8 are
  replaced.
- `follow_log` starts after the last `tail` lines, none by default, or at `offset`: pass the
  `offset` of the last line read to carry on from it.
- A follow asks Odoo.sh every second and ends when the iterator is closed. After `timeout` seconds
  it raises `StreamTimeoutError`. `timeout=math.inf` sets no limit.
- A request that fails is sent again twice, from where the last one stopped, so no line is lost
  or repeated. Then `UpstreamUnavailableError` is raised.
- Each call asks Odoo.sh for the build's worker and the project's access token before the log.
  [Security](security.md#build-logs) says what happens to the token.

### A shell on a build

`client.ssh_target(build)` returns the `SshTarget` of a build: the `user` and the `host` that
`ssh` reaches it with. Odoo.sh is not asked, and the library opens no connection and reads no key.

```python
import odouche


with odouche.Client() as client:
    build = client.build(51044, 88212)
    target = client.ssh_target(build)
print("ssh", "-l", target.user, target.host)
```

- Both values are checked to be safe as arguments of `ssh`: one that is not raises
  `UpstreamChangedError`.
- A build with no address raises `NotFoundError`.

A build host accepts SSH only from an address Odoo.sh allows, and no request of Odoo.sh tells
whether this machine's is. `client.allow_ip(branch)` allows it: see
[State-changing operations](#state-changing-operations).

### A build's panels

`client.panel_url(project, branch, build, panel)` returns the address of a build's monitor, shell
or editor, for a browser to open. `panel` is a `Panel` (`MONITOR`, `SHELL` or `EDITOR`) or its
name, and `build` a build of `branch`.

```python
import odouche


with odouche.Client() as client:
    branches = {branch.name: branch for branch in client.branches("acme-shop")}
    branch = branches["feature-invoicing"]
    build = client.latest_build(branch)
    if build is None:
        raise SystemExit("The branch has no build yet.")
    try:
        print(client.panel_url("acme-shop", branch, build, odouche.Panel.SHELL))
    except odouche.NotFoundError as error:
        print(error)
```

- Odoo.sh is not asked: the URL is built from the build and its branch, and only reads.
- A build has panels once it is `DONE`, as on the page. Any other raises `NotFoundError`, which
  says when the build is still waiting for a worker.
- The shell and the editor are on the build's own host. The monitor is the branch's, on
  `www.odoo.sh`, and shows its latest build: only a staging or a production branch has one.
- No URL carries a token or the session. The browser that opens it signs in to Odoo.sh on its own.
- A build address that is not a bare host under `odoo.com` raises `UpstreamChangedError`.

## State-changing operations

Every other call of the client only reads. These are the calls that change something on Odoo.sh:

| Call | What it changes |
| --- | --- |
| `client.rebuild(branch)` | Starts a new build of the branch, which replaces its latest one. |
| `client.allow_ip(branch)` | Lets this machine's address connect with `ssh` for one hour, to the branch's builds and, as [seen](upstream.md#allow-an-ip), the project's others. |
| `client.create_backup(project, branch)` | Takes a manual backup of the branch's latest build, which Odoo.sh keeps for three days. |
| `client.prepare_download(project, backup)` | Has Odoo.sh prepare the backup's file, which it keeps for 2 hours. |

```python
import odouche


with odouche.Client() as client:
    branches = {branch.name: branch for branch in client.branches("acme-shop")}
    branch = branches["feature-invoicing"]
    build = client.rebuild(branch)
    for build in client.watch_build("acme-shop", build, timeout=1800):
        print(build.status, build.status_info)
```

- `odouche.Client(read_only=True)` refuses them: the call raises `ReadOnlyError` and nothing is
  sent, not even the reads the call starts with. `client.read_only` tells which a client is.
- The request is sent once and never repeated. When it left and Odoo.sh did not confirm it, or
  the new build cannot be found, the call raises `OutcomeUnknownError`: look at the branch before
  calling again, since a second call can start a second build.
- `rebuild` takes a `Branch` or a branch's number and returns the new `Build`. It asks Odoo.sh
  three times: for the branch's latest build, for the rebuild, then for the new build.
- Only a development or a staging branch is rebuilt. Any other stage raises `StageRefusedError`
  before the rebuild is sent, and before any request when a `Branch` in that stage is passed.
  A rebuild has only been observed on a development branch.
- `client.check_rebuild(branch)` raises the same `StageRefusedError` for a `Branch` and asks
  nothing, on a read-only client too: call it before asking the user.
- `allow_ip` takes a `Branch` or a branch's number and returns the address Odoo.sh allowed, an
  `ipaddress.IPv4Address` or `IPv6Address`. It sends no address: Odoo.sh takes the one the
  request comes from, which is a proxy's when one is in the environment. Odoo.sh says the rule
  lasts one hour and takes up to five minutes to apply; one was seen to take longer. A user whose access does not reach the branch's stage
  is expected to get `PermissionDeniedError`.
- The library asks for no confirmation. That is the caller's to do.
- `create_backup` takes the project and the branch, each as a model or by its name or number,
  and an optional `comment`, and returns a `BackupRequest`, which names the `build` backed up. Odoo.sh answers nothing about the backup, so `client.wait_for_backup(project,
  request, timeout=...)` asks for the project's backups every five seconds and yields `None`
  until the new manual backup of that build is listed and Odoo.sh has finished it, then that
  `Backup`. It raises `StreamTimeoutError` at the timeout. A backup has been seen listed 58
  seconds after the request and finished 19 seconds later; Odoo.sh refuses a file of it until then.
- Only a staging or a production branch is backed up, checked as for a rebuild, with
  `client.check_backup(branch)`. A backup has only been observed on a staging branch.

```python
import odouche


with odouche.Client() as client:
    request = client.create_backup("acme-shop", 51044, comment="before the upgrade")
    for backup in client.wait_for_backup("acme-shop", request, timeout=600):
        if backup is not None:
            print(backup.taken_at)
```

- `prepare_download` takes the project and a `Backup` that is `downloadable`, and
  `neutralized=False` for the exact database or `filestore=False` to leave the filestore out. It
  returns a `PreparedDownload`, whose `link` is the page's link to the file. It is sent on the build
  the backup was taken from, and raises `NotFoundError` once that build is no longer among its
  branch's latest. `client.wait_for_download(project, prepared, timeout=...)` asks for the
  project's notifications every five seconds and yields `None` until Odoo.sh says the file is
  ready, which took 30 seconds for a small database. Preparing twice does no harm.
- `client.find_download(project, backup)` takes the same choices and returns the
  `PreparedDownload` of a file Odoo.sh already holds, or `None`. It only reads: it looks for the
  notification of the file, then opens the file once to tell it is still there. Odoo.sh says it
  keeps a file for 2 hours.
- `client.download(prepared)` is a context manager that gives a `BackupFile`: its `size`, when
  Odoo.sh says it, and its `chunks` as they arrive. Odoo.sh hands over a token for the file, which
  is sent to the build's worker alone and kept nowhere: the token grants the file to whoever holds
  it. Where the file is written, and who may read it, is the caller's to decide.

```python
import os

import odouche


with odouche.Client() as client:
    backup = next(found for found in client.backups("acme-shop") if found.downloadable)
    prepared = client.find_download("acme-shop", backup)
    if prepared is None:
        prepared = client.prepare_download("acme-shop", backup)
        for _ in client.wait_for_download("acme-shop", prepared, timeout=600):
            pass
    private = os.open("backup.zip", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with client.download(prepared) as file, open(private, "wb") as out:
        for chunk in file.chunks:
            out.write(chunk)
```

## Errors

Everything the library raises is an `OdoucheError`, so one `except` catches any failure and no
HTTP client exception has to be imported.

```python
import odouche


try:
    with odouche.Client() as client:
        names = [project.name for project in client.projects()]
except (odouche.NoSessionError, odouche.SessionExpiredError):
    raise SystemExit("Log in to Odoo.sh first.") from None
except odouche.OdoucheError as error:
    raise SystemExit(str(error)) from None
print(names)
```

| Error | Meaning |
| --- | --- |
| `NoSessionError` | There is no session. Log in. |
| `SessionExpiredError` | Odoo.sh rejected the session, or it passed its max age. Log in again. |
| `NotFoundError` | The project, branch, build or log is not one the session's user can reach. |
| `PermissionDeniedError` | The session is not allowed to do this. |
| `UpstreamChangedError` | Odoo.sh answered in a shape the library does not read. Please report it. |
| `UpstreamUnavailableError` | Odoo.sh could not be reached, or answered with a server error. |
| `ReadOnlyError` | A read-only client was asked to change state. Nothing was sent. |
| `StageRefusedError` | The branch is in a stage the library does not change. |
| `OutcomeUnknownError` | A state-changing request was sent and Odoo.sh did not confirm it. Look before trying again. |
| `StreamTimeoutError` | A build was still being watched, or a log followed, at its timeout. |
| `KeyringUnavailableError` | No accepted keyring backend is available to store the session. |
| `LoginError` | The login ended without a session, or the pasted one was refused. |
| `LoginTimeoutError` | Nobody completed the browser login before its timeout. |

An error carries `operation`, `status` and a message. It never carries a session value, request
headers or a response body.

## Stability

- **The public API is what `odouche` exports**: the names in `odouche.__all__`, which the
  [API reference](reference.md) lists one by one. A module or a name with a leading underscore,
  `odouche._upstream` included, is not, and changes without notice.
- **Below 1.0, a minor release can break the public API** and a patch release does not. The
  [changelog](https://github.com/avanserv/odouche/blob/main/CHANGELOG.md) marks each breaking
  change.
- **Odoo.sh can break the library in any release**, since it has no public API. A caller sees
  that as `UpstreamChangedError`, whose `operation` and `field` name the request and what could
  not be read in its answer. No retry helps, and the input is not at fault.
- **Report one** on the [issue tracker](https://github.com/avanserv/odouche/issues) with the
  error's message, which holds no session value. Leave out the answer itself: it holds your
  projects' data.
