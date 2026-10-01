# MCP server

`odouche-mcp` is a [Model Context Protocol](https://modelcontextprotocol.io) server that lets
development agents work with your Odoo.sh projects.

```bash
uvx odouche-mcp
```

!!! note "Not implemented yet"

    The server starts over stdio and exposes no tools. This page will document each tool, what it
    does and what it can touch, as the tools land.

## Design constraints

- **Read-only by default.** Tools that change state on Odoo.sh are opt-in and documented as such.
- **Every tool is documented.** What it does, and what it can touch.
- **No credentials in results.** Session values never appear in a tool result.

The server is built on the [`odouche` library](library.md) and never talks to Odoo.sh directly.
