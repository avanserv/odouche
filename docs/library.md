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
- **Streaming where it matters.** Long-running operations, such as watching a build or following
  logs, are exposed as iterators rather than as blocking calls.

The generated [API reference](reference.md) lists everything the library exports.
