# Library

`odouche` is the Python client for Odoo.sh that the command-line tool and the MCP server are built
on. It is meant to be used directly in your own tools as well.

```bash
uv add odouche
```

!!! note "Being built"

    Logging in works. Projects, branches, builds and logs are not implemented yet; this page
    documents the client as it lands.

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

## Errors

Everything the library raises is an `OdoucheError`, so one `except` catches any failure and no
HTTP client exception has to be imported.

| Error | Meaning |
| --- | --- |
| `NoSessionError` | There is no session. Log in. |
| `SessionExpiredError` | Odoo.sh rejected the session, or it passed its max age. Log in again. |
| `NotFoundError` | The project, branch or build does not exist. |
| `PermissionDeniedError` | The session is not allowed to do this. |
| `UpstreamChangedError` | Odoo.sh answered in a shape the library does not read. Please report it. |
| `UpstreamUnavailableError` | Odoo.sh could not be reached, or answered with a server error. |
| `KeyringUnavailableError` | No accepted keyring backend is available to store the session. |
| `LoginError` | The login ended without a session, or the pasted one was refused. |
| `LoginTimeoutError` | Nobody completed the browser login before its timeout. |

An error carries `operation`, `status` and a message. It never carries a session value, request
headers or a response body.

The generated [API reference](reference.md) lists everything the library exports.
