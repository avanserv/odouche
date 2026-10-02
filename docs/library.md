# Library

`odouche` is the Python client for Odoo.sh that the command-line tool and the MCP server are built
on. It is meant to be used directly in your own tools as well.

```bash
uv add odouche
```

!!! note "Not implemented yet"

    The package installs and imports, and exposes its version. The client is being built; this
    page will document it as it lands.

```python
import odouche

print(odouche.__version__)
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

An error carries `operation`, `status` and a message. It never carries a session value, request
headers or a response body.

The generated [API reference](reference.md) lists everything the library exports.
