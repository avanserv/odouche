# Library

`odouche` is the Python client for Odoo.sh that the command-line tool and the MCP server are built
on. It is meant to be used directly in your own tools as well.

```bash
uv add odouche
```

!!! note "Being built"

    Logging in and listing projects, branches and builds work. Watching a build, logs and
    rebuilding are not implemented yet; this page documents the client as it lands.

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

- The library neither prints nor prompts. `notify` is called with a `LoginStep`: `BROWSER` when
  the window is open, `PASTE` when no browser can be launched and `ask` is about to be called.
- `ask` returns the pasted cookie, wrapped in a `Secret`. Without it, a machine with no browser to
  launch gets a `LoginError`.
- The session is stored once Odoo.sh has answered one request sent with it. A login that is
  refused or times out leaves the stored session as it was.
- A login nobody completes raises `LoginTimeoutError` after `timeout` seconds.
- Called from the main thread, a login that `SIGTERM` or `SIGHUP` ends deletes the browser profile
  before the signal takes effect.
- With no keyring to store the session in, or one that stays locked, `KeyringUnavailableError` is
  raised before the browser opens.

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
- With no session, `Client()` raises `NoSessionError`.
- Nothing is cached: each call asks Odoo.sh.

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

## Errors

Everything the library raises is an `OdoucheError`, so one `except` catches any failure and no
HTTP client exception has to be imported.

| Error | Meaning |
| --- | --- |
| `NoSessionError` | There is no session. Log in. |
| `SessionExpiredError` | Odoo.sh rejected the session, or it passed its max age. Log in again. |
| `NotFoundError` | The project, branch or build is not one the session's user can reach. |
| `PermissionDeniedError` | The session is not allowed to do this. |
| `UpstreamChangedError` | Odoo.sh answered in a shape the library does not read. Please report it. |
| `UpstreamUnavailableError` | Odoo.sh could not be reached, or answered with a server error. |
| `KeyringUnavailableError` | No accepted keyring backend is available to store the session. |
| `LoginError` | The login ended without a session, or the pasted one was refused. |
| `LoginTimeoutError` | Nobody completed the browser login before its timeout. |

An error carries `operation`, `status` and a message. It never carries a session value, request
headers or a response body.

The generated [API reference](reference.md) lists everything the library exports.
