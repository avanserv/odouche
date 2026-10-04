# Library

`odouche` is the Python client for Odoo.sh that the command-line tool and the MCP server are built
on. It is meant to be used directly in your own tools as well.

```bash
uv add odouche
```

!!! note "Being built"

    Logging in and out, the session's user, listing projects, branches and builds, and build logs
    work. Watching a build and rebuilding are not implemented yet; this page documents the client
    as it lands.

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

### Builds

`client.builds(branch)` returns the latest builds of a branch, newest first, as a list of `Build`.
`branch` is a `Branch` or a branch's number.

```python
with odouche.Client() as client:
    branch = client.branches("acme-shop")[0]
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
with odouche.Client() as client:
    build = client.latest_build(branch)
    for line in client.read_log("acme-shop", build, odouche.LogKind.INSTALL, tail=20):
        print(line.text)
    for line in client.follow_log("acme-shop", build, odouche.LogKind.ODOO, timeout=600):
        print(line.text)
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
- A line longer than 64 KiB is cut to that and marked `truncated`. Bytes that are not UTF-8 are
  replaced.
- `follow_log` starts after the last `tail` lines, none by default, or at `offset`: pass the
  `offset` of the last line read to carry on from it.
- A follow asks Odoo.sh every second and ends when the iterator is closed. After `timeout` seconds
  it raises `StreamTimeoutError`.
- A request that fails is sent again twice, from where the last one stopped, so no line is lost
  or repeated. Then `UpstreamUnavailableError` is raised.
- Each call asks Odoo.sh for the build's worker and the project's access token before the log.
  [Security](security.md#build-logs) says what happens to the token.

## Errors

Everything the library raises is an `OdoucheError`, so one `except` catches any failure and no
HTTP client exception has to be imported.

| Error | Meaning |
| --- | --- |
| `NoSessionError` | There is no session. Log in. |
| `SessionExpiredError` | Odoo.sh rejected the session, or it passed its max age. Log in again. |
| `NotFoundError` | The project, branch, build or log is not one the session's user can reach. |
| `PermissionDeniedError` | The session is not allowed to do this. |
| `UpstreamChangedError` | Odoo.sh answered in a shape the library does not read. Please report it. |
| `UpstreamUnavailableError` | Odoo.sh could not be reached, or answered with a server error. |
| `StreamTimeoutError` | A log was still being followed at its timeout. |
| `KeyringUnavailableError` | No accepted keyring backend is available to store the session. |
| `LoginError` | The login ended without a session, or the pasted one was refused. |
| `LoginTimeoutError` | Nobody completed the browser login before its timeout. |

An error carries `operation`, `status` and a message. It never carries a session value, request
headers or a response body.

The generated [API reference](reference.md) lists everything the library exports.
