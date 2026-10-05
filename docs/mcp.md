# MCP server

`odouche-mcp` is a [Model Context Protocol](https://modelcontextprotocol.io) server that lets
development agents work with your Odoo.sh projects.

```bash
uvx odouche-mcp
```

The server starts over stdio. Started this way its tools read: none changes anything on Odoo.sh.
The one tool that does is [yours to turn on](#changing-state). This page documents each tool, what
it does and what it can touch.

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

### `read_log`

Reads the last lines of one log of a build: of the build of `build_id`, or of the branch's latest
one. Without `kind`, it reads the install log when the build has it and the odoo log otherwise.
With `contains`, only the lines that hold that text are returned, out of the log's last mebibyte.
The text is matched as it is, case included, and not as a pattern.

The lines come in `untrusted_lines`, without their escape sequences and control characters, and
are [not instructions](#build-logs). `truncated` is true when the last mebibyte held more lines
than returned, or one was cut. It says nothing of what the log holds before that, which is not read.

- **Arguments**: `project`, `branch` as the git branch's name, and optionally `build_id`, `kind`
  (`install`, `pip`, `odoo`, `update`, `neutralize` or `upgrade`), `lines`, 100 by default and 500
  at most, and `contains`.
- **Touches**: reads only.
- **Bounds**: seven requests to Odoo.sh and the build's worker, ten when no `kind` is given. The
  lines take 65536 bytes at most together, as JSON: past that, the oldest are left out. A result
  carries them twice, as text and as structured content.

### `rebuild_branch`

Changes state on Odoo.sh: starts a new build of a branch, which replaces its latest one. It is
listed only when the server is started with [`--allow-changes`](#changing-state). Only a
development or a staging branch is rebuilt: any other is refused before the rebuild is sent.

It returns the new build, in progress. The request is sent once and never repeated. When Odoo.sh
does not confirm it, or the new build cannot be found, the error says so and tells the agent to
list the branch's builds before trying again, since a second call can start a second build.

- **Arguments**: `project`, and `branch` as the git branch's name.
- **Touches**: starts a new build of the branch, which replaces its latest one.
- **Bounds**: five requests to Odoo.sh.

## Changing state

The tools that change state on Odoo.sh are off until you start the server with `--allow-changes`:

```json
{
  "mcpServers": {
    "odouche": { "command": "uvx", "args": ["odouche-mcp", "--allow-changes"] }
  }
}
```

- The flag is read once, when the server starts. No tool and no argument sets it, so nothing an
  agent does during a session turns it on.
- Without it, `rebuild_branch` is not registered, and every tool opens the library's client
  read-only, which refuses a change before anything is sent.
- With it, `rebuild_branch` is listed without the read-only hint and with the destructive one, so
  a client that asks before such tools asks before this one. The server itself does not ask.
- Each call writes one line to the server's stderr: the tool, the project, the branch, and the
  build started or the kind of error. It never holds the session.

## Arguments and results

### The project

The project is always an argument. The server does not read it from a git checkout: its working
directory is wherever the client started it, and a guess could point an agent at the wrong
project. A call without one is rejected.

### Limits

A list holds at most `limit` items, and `truncated` is true when there were more. A `limit` over
the most a tool returns is lowered to it, and one below 1 is an error. The `lines` of `read_log`
follow the same rule.

### Untrusted text

Branch names, commit messages and author names are written by other people. The server returns
them in the fields of a result only, never in a sentence of its own, and a client should treat
them as data, not as instructions.

### Build logs

A log is whatever the build printed: the output of every module, and of every request made to the
instance. Anyone who can make it print a line can write one that reads as an instruction to an
agent, and a log can hold a secret of the instance.

- `read_log` returns the lines in one field, `untrusted_lines`, and its description tells the
  agent that they are data and are not to be followed. That lowers the risk of prompt injection.
  It does not remove it: an agent can still act on what it reads.
- Secrets are not masked. A mask would catch some and promise all, so the lines pass through as
  they are, into the agent's context and whatever the client does with it.
- No line of a log is written to the server's stderr.

This is why the server is read-only unless you [start it otherwise](#changing-state): an agent
misled by a log has no tool that changes anything on Odoo.sh. Whether an agent may call a tool
without asking you is your client's decision, and every tool carries the
[hints](#tool-contract) a permission rule can use.

## Design constraints

- **Read-only by default.** Tools that change state on Odoo.sh are [opt-in](#changing-state) and
  documented as such.
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
