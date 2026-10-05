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

## Tool contract

Every tool follows the same rules, and a test over the registered tools holds them to it.

- **Names** are a verb then a noun, such as `list_projects` or `get_build`, and do not change
  once released: permission rules and hooks match on them.
- **Descriptions** end with three labelled lines: `Returns:` what the tool returns, `Touches:`
  what it can change on Odoo.sh, and `Bounds:` its limits on size and time. A tool that changes
  nothing says `Touches: reads only`.
- **Annotations** are all set. A tool that reads has the read-only hint, and a client can use the
  hints to decide when to ask you first.
- **Results** are structured, with the field names of the [library's models](reference.md), which
  are also what `osh --format json` prints.
- **Errors** are a message and, when there is one, the next step: never a traceback or an answer
  from Odoo.sh.

The server is built on the [`odouche` library](library.md) and never talks to Odoo.sh directly.
