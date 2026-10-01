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

The generated [API reference](reference.md) lists everything the library exports.
