# MCP server

`odouche-mcp` is a [Model Context Protocol](https://modelcontextprotocol.io) server that lets
development agents work with your Odoo.sh projects.

```bash
uvx odouche-mcp
```

The server starts over stdio. Its tools read: none changes anything on Odoo.sh. This page
documents each one, what it does and what it can touch.

## Session

The server cannot log in, and has no tool that does: a browser opened because an agent asked is
a phishing surface. It uses the session you already have:

1. `ODOUCHE_SESSION`, when it is set in the server's environment. It is kept in memory only.
2. The session `osh auth login` stored in the keyring.

The session is looked up on each call, not when the server starts. The server starts and lists
its tools while you are logged out, and an `osh auth login` made while it runs is used by the
next call, with no restart. No tool takes a session as an argument.

With no session, an expired one or no usable keyring, a tool's error tells the agent to stop and
ask you to run `osh auth login` in a terminal, or to restart the server with `ODOUCHE_SESSION`
set where there is no keyring. When the session comes from `ODOUCHE_SESSION`, it says to restart
the server with a current value or without the variable, since a login would not be read.

## Tools

### `get_session`

Reports whether the server has a session, whether it came from the environment or the keyring,
the user it belongs to and the seconds left before its [max age](security.md). It never returns
the session. With none, `available` is false and `problem` says what to do. A session Odoo.sh
rejects is an error, as from any other tool.

- **Touches**: reads only.
- **Bounds**: one request to Odoo.sh, none when there is no session.

### `list_projects`

Lists the projects you can reach, each with its name, repository and address. Every other tool
takes a project by its name, so an agent calls this one first.

- **Arguments**: `limit`, 50 by default and 200 at most.
- **Touches**: reads only.
- **Bounds**: one request to Odoo.sh.

### `list_branches`

Lists the branches of a project, each with its name and stage, in the order Odoo.sh answers them.

- **Arguments**: `project`, and `limit`, 50 by default and 200 at most.
- **Touches**: reads only.
- **Bounds**: two requests to Odoo.sh.

### `list_builds`

Lists the latest builds of a branch, newest first, with their status, result and commit.

- **Arguments**: `project`, `branch` as the git branch's name, and `limit`, 4 by default and 20
  at most.
- **Touches**: reads only.
- **Bounds**: three requests to Odoo.sh. Odoo.sh has only been seen to answer 4 builds: older
  ones are out of reach, whatever `truncated` says.

### `get_build`

Reads one build of a branch, with its commit and the address of its database: the build of
`build_id`, or the branch's latest one.

- **Arguments**: `project`, `branch` as the git branch's name, and optionally `build_id`.
- **Touches**: reads only.
- **Bounds**: three requests to Odoo.sh. A build older than the branch's latest ones is not found.

## Arguments and results

### The project

The project is always an argument. The server does not read it from a git checkout: its working
directory is wherever the client started it, and a guess could point an agent at the wrong
project. A call without one is rejected.

### Limits

A list holds at most `limit` items, and `truncated` is true when there were more. A `limit` over
the most a tool returns is lowered to it, and one below 1 is an error.

### Untrusted text

Branch names, commit messages and author names are written by other people. The server returns
them in the fields of a result only, never in a sentence of its own, and a client should treat
them as data, not as instructions.

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
