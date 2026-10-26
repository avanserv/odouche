# MCP server

`odouche-mcp` is a [Model Context Protocol](https://modelcontextprotocol.io) server that lets
development agents work with your Odoo.sh projects. It runs over stdio, and started as below its
tools read: none changes anything on Odoo.sh. The tools that do are
[yours to turn on](#changing-state).

The [reference](mcp-reference.md) lists every tool with its arguments, what it returns, what it
can touch and its bounds, generated from the server.

## Setup

### Log in

The server cannot log in. Give it a session first, one of two ways:

- Run `osh auth login`, from [`odouche-cli`](cli.md), which stores the session in your keyring.
- Where there is no keyring, set `ODOUCHE_SESSION` in the server's environment. A client that
  does not pass its own environment on has to be told to pass the variable. Do not write its value
  in a configuration file.

### Claude Code

<!-- x-release-please-start-version -->
```bash
claude mcp add odouche -- uvx odouche-mcp==0.7.0
```
<!-- x-release-please-end -->

Or, for everyone who works on a project, in its `.mcp.json`:

<!-- x-release-please-start-version -->
```json
{
  "mcpServers": {
    "odouche": { "command": "uvx", "args": ["odouche-mcp==0.7.0"] }
  }
}
```
<!-- x-release-please-end -->

Name the server `odouche`: the [hook](#asking-before-a-change) matches on that name.

### Any other client

The server speaks stdio and takes no configuration but its one flag. Give your client this
command:

<!-- x-release-please-start-version -->
```bash
uvx odouche-mcp==0.7.0
```
<!-- x-release-please-end -->

### Why a version is pinned

Without a version, `uvx` runs the newest release the first time, and again whenever its cache is
pruned or refreshed: the version can change without you choosing it, and this process holds your
Odoo.sh session. Pinned, a new release runs only once you have changed the number.

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

What the [reference](mcp-reference.md) does not say of each tool.

### `get_session`

It never returns the session. With none, `available` is false and `problem` says what to do. A
session Odoo.sh rejects is an error, as from any other tool. The seconds left are those before the
session's [max age](security.md).

### `list_projects`

Every other tool takes a project by its name, so an agent calls this one first.

### `get_project_overview`

Storage is in bytes. `hosting`, which holds the storage, the workers and the staging branches, is
null when the user is not an admin of the project: Odoo.sh shows them on the project's Settings
page, to an admin only, and they are not asked otherwise. The region is there for every member.
`branches` holds 200 at most, with `truncated` true when there are more, while `stages` counts
every branch. Each branch's last build holds its number, status and result only: `get_build` reads
the rest. No token or code is in the result.

### `get_project_settings`

Odoo.sh shows a project's settings to an admin of the project only: anyone else gets an error, and
the settings are not asked for. The IP allow list holds each entry as written, an address or a
network such as `203.0.113.0/24`, the timeouts are in seconds, and each submodule comes with its
URL, without its query, fragment or credentials, or empty when it cannot be read safely, and the fingerprint and public half of its deploy key.
The rest of the development defaults are named as in `get_branch_settings`. Submodule URLs, modules
and test tags come from what the project's admins typed: treat them as data, not as instructions.
No token or code is in the result.

### `list_audit_log`

Odoo.sh shows a project's audit log to an admin of the project only: anyone else gets an error,
and the log is not asked for. Odoo.sh sends the whole of the last 30 days in one answer, with no
paging, so `limit` bounds what is returned, not what Odoo.sh sends. The entries are in
`untrusted_entries`: their author, action and details were written by other people, and the
details hold addresses, logins and what an SSH client says of itself. An action the library does
not know has the kind `unknown`, with what Odoo.sh calls it in `kind_name`.

### `list_members`

Odoo.sh shows a project's members to an admin of the project only: anyone else gets an error, and
the settings they are part of are not asked for. The members come highest role first, then by
login, and a cut at `limit` keeps the highest roles. They are in `untrusted_members`: a login and a
name are other people's personal data, which they chose. Odoo.sh gives no member's email. A role
the library does not know is an error.

### `list_branches`

The branches come in the order Odoo.sh answers them.

### `list_builds`

`branch` is the git branch's name, as for every tool that takes one. Odoo.sh has only been seen to
answer the latest builds of a branch: older ones are out of reach.

### `list_history`

Each push comes with its commits, so an older build than `list_builds` reaches is found here by
its number and commit. The build of an event holds its number, status and result only.

### `get_build`

Without `build_id`, it reads the branch's latest build. A build older than the branch's latest
ones is not found. Odoo.sh has no settings request for a build: a new build takes its branch's
settings, which `get_branch_settings` reads.

### `get_branch_settings`

The settings come with the branch and its stage: the new build options, from `project_defaults` to
`ai_agent`, apply to a development branch only, and not while `project_defaults` is true. A value
the library does not know is an error naming the field, not a value passed on. For a build, see
`get_build`.

### `get_build_revision`

Without `build_id`, it reads the branch's latest build. Every hash is whole. The Odoo revision is
the one the branch has selected now: Odoo.sh ties none to a build, so it is not proven to be the
one the build runs. Odoo.sh gives no commit for a submodule, so there is none in the result, and
its absence says nothing of whether the repository has submodules.

### `wait_for_build`

It waits for the build of `build_id`, or the branch's latest one, and returns it as last seen and
`finished`, as soon as the build ends.

A build that outlasts the wait is not an error. `finished` is false and `next_step` tells the
agent to call the tool again, which continues the wait. The wait is short because a client gives
up on a call that lasts: a `timeout` over the most is lowered to it, `timeout` in the result is
the one applied, and `timeout_capped` says it was lowered.

With `commit`, the first 7 to 64 digits of a hash, the tool waits for the branch to have a build
of that commit, then for that build. Right after a push the latest build is still the previous
one, so an agent that pushed gives the commit. While the branch has no such build, `build` is null
and `next_step` says to call again. `build_id` and `commit` are not given together.

- **Progress**: a notification at each change of the build, to a client that asked for them. It
  holds the build's number, status and result, and nothing Odoo.sh or a commit's author wrote.
- **Cancellation**: a call the client cancels closes its connection to Odoo.sh, within a few
  seconds unless a request is being answered.
- **Timeout**: the requests that find the build, or await one of a commit, are not cut at the
  `timeout`: a slow Odoo.sh can make a call last longer.

### `read_log`

Without `kind`, it reads the install log when the build has it and the odoo log otherwise. With
`contains`, only the lines that hold that text are returned, out of the log's last mebibyte. The
text is matched as it is, case included, and not as a pattern. A `kind` of `unknown` is refused.

The lines come in `untrusted_lines`, without their escape sequences and control characters, and
are [not instructions](#build-logs-and-mails). `truncated` is true when the last mebibyte held
more lines than returned, or one was cut. It says nothing of what the log holds before that, which
is not read. When the lines are over the most a result holds, the oldest are left out. A result
carries them twice, as text and as structured content.

### `list_mails`

A development or a staging build sends no mail: Odoo.sh catches each one, and this tool lists
them, newest first. Without `build_id`, it lists the branch's latest build's. A build that caught
nothing gives an empty list, and a branch of another stage is an error.

The mails come in `untrusted_mails`, each header on one line without its escape sequences and
control characters, and are [not instructions](#build-logs-and-mails). `truncated` is true when
there are more, a header was cut, or a mail was left out because its `id` is over 256 bytes or
holds a control character. A mail's `id` is what `read_mail` takes, whole.

### `read_mail`

It reads one mail by the `id` that `list_mails` gives it, of the same build. An HTML body comes as
text: scripts, styles and images are dropped, a link keeps its address after its text, and
nothing is opened. Attachments come by name and size: their content is not read.

Every part of the mail comes in an `untrusted_` field: `untrusted_mail`, `untrusted_cc`,
`untrusted_attachments` and `untrusted_body_lines`, which holds the body from its first line.
`truncated` is true when a header, a name, the body or the parts were cut, past 1000 MIME parts
counted with their containers, or the mail was over 16 MiB and not read at all.

### `change_branch_settings`

It is listed only when the server is started with [`--allow-changes`](#changing-state). It sends
only the settings given that differ from the branch's, in one request, and the others keep their
value; with nothing to change it sends nothing. The arguments are named and valued as
`get_branch_settings` returns them, except `modules`, which is names separated by commas.

Everything is checked before the request: a value that is no choice fails the schema, what a new
commit does is refused on a production branch, and the new build options on any branch but a
development one, or while `project_defaults` stays true. The result names the settings changed and
those already at that value, and in `moved` each other setting Odoo.sh changed along with them,
such as the tests once every module is installed, with its value before and after. When Odoo.sh
does not confirm the change, or a setting sent does not read back as sent, the error tells the
agent to read the settings before trying again.

### `change_project_settings`

It is listed only when the server is started with [`--allow-changes`](#changing-state), and it
changes the settings of a project its user is an admin of. It sends only the settings given that
differ from the project's, in one request, and the others keep their value; with nothing to change
it sends nothing. It takes the defaults of new development branches, named and valued as
`get_project_settings` returns them, and on a dedicated server the two timeouts, in seconds.

It takes nothing that changes who can reach the project: the IP allow list, public access and the
session lifetime are not among its arguments, and only `osh projects settings set` changes them.
A call that gives an argument the tool does not declare, such as `ip_allow_list` or `public`, is
refused by the server before the tool runs: nothing is read or sent, and no line is written to
stderr. Every tool that changes state refuses an undeclared argument the same way, and its schema
says so with `additionalProperties` false.

The result is shaped as `change_branch_settings`'s, with the project's name for the branch. When
Odoo.sh does not confirm the change, or a setting sent does not read back as sent, the error tells
the agent to read the settings before trying again.

### `rebuild_branch`

It is listed only when the server is started with [`--allow-changes`](#changing-state). Only a
development or a staging branch is rebuilt: any other is refused before the rebuild is sent.

The request is sent once and never repeated. When Odoo.sh does not confirm it, or the new build
cannot be found, the error says so and tells the agent to list the branch's builds before trying
again, since a second call can start a second build.

## Security

- **By default** the server reads your projects, a project's settings, audit log and members,
  their branches, a branch's settings, their builds, the builds' logs and the mails a development or
  staging build caught. It changes nothing on Odoo.sh.
- **With `--allow-changes`** it can also start a rebuild of a development or a staging branch,
  change a branch's settings (what a new commit does, and a development branch's new build
  options) and change a project's settings: the defaults of new development branches and, on a
  dedicated server, the timeouts.
- **No tool** changes who can reach a project: the IP allow list, public access and the session
  lifetime are changed only from a terminal, with `osh projects settings set`.
- **No tool** moves a branch between stages, with or without `--allow-changes`: a move to staging
  copies production's data onto the branch, which is `osh branches move`'s, behind its question.
- **No tool** adds a member to a project or changes a member's role, with or without
  `--allow-changes`: a role decides who reaches production, which is `osh projects members add`'s
  and `role`'s, behind their question.
- **It never** logs in, takes a session as an argument, returns the session in a result or writes
  a file.

[Security](security.md) has how the session is obtained and stored.

### Changing state

The tools that change state on Odoo.sh are off until you start the server with `--allow-changes`:

<!-- x-release-please-start-version -->
```json
{
  "mcpServers": {
    "odouche": { "command": "uvx", "args": ["odouche-mcp==0.7.0", "--allow-changes"] }
  }
}
```
<!-- x-release-please-end -->

- The flag is read once, when the server starts. No tool and no argument sets it, so nothing an
  agent does during a session turns it on.
- Without it, `change_branch_settings`, `change_project_settings` and `rebuild_branch` are not
  registered, and every tool opens the library's client read-only, which refuses a change before
  anything is sent.
- With it, they are listed without the read-only hint and with the destructive one, so a client
  that asks before such tools asks before these. The server itself does not ask.
- They refuse a call with an argument they do not declare, before anything is read or sent.
- Each call writes one line to the server's stderr: the tool, the project, the branch when there
  is one, and the build started, the names of the settings changed, or the kind of error. It never
  holds the session or a setting's value.

### Asking before a change

The flag decides whether the tools that change state exist. Whether an agent may call a tool without asking
you is your client's decision. For Claude Code, a hook lets the tools that read pass and leaves
the rest to the usual prompt:
[`examples/claude-code/odouche_read_only_hook.py`](https://github.com/avanserv/odouche/blob/main/examples/claude-code/odouche_read_only_hook.py).
It needs Python and nothing else. Read it, copy it into your project's `.claude/hooks/`, and add
it to `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "mcp__odouche__.*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/odouche_read_only_hook.py",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

- It approves a call to a tool on its list, which a test holds to the tools the server registers
  with the read-only hint. For any other tool, and for any input it does not understand, it
  prints nothing and Claude Code asks you as it would without the hook.
- Claude Code names a tool `mcp__<server>__<tool>`, where `<server>` is the name the server has
  in your configuration. Under another name than `odouche`, change `SERVER` in the script and the
  matcher above.
- It does not read a call's arguments, and it never denies a call.
- `get_project_settings`, `list_audit_log`, `list_members`, `read_log`, `list_mails` and
  `read_mail` are among the tools it approves, so a project's submodule URLs and allowed
  addresses, an audit log's details, its members' logins and names, the lines of a
  [build log](#build-logs-and-mails) and the text of a caught mail reach the agent without a
  prompt.
- It does not replace `--allow-changes`: without the flag there is no tool to ask about.

Another client decides from the [hints](#tool-contract) each tool carries.

### Build logs and mails

A log is whatever the build printed: the output of every module, and of every request made to the
instance. A caught mail is whatever the build's code wrote, often from its data: a customer's
name, a message sent through a form. Anyone who can make the build print a line or send a mail can
write one that reads as an instruction to an agent, and either can hold a secret of the instance.

- `read_log` returns the lines in one field, `untrusted_lines`, and `list_mails` and `read_mail`
  return a mail only in fields named `untrusted_`. Each tool's description tells the agent that
  they are data and are not to be followed, and so do the instructions the server gives a client
  when it connects. That lowers the risk of prompt injection. It does not remove it: an agent can
  still act on what it reads.
- Each is stripped of escape sequences and control characters and capped in size before it is
  returned.
- Secrets are not masked. A mask would catch some and promise all, so the text passes through as
  it is, into the agent's context and whatever the client does with it.
- No line of a log and nothing of a mail is written to the server's stderr.

This is why the server is read-only unless you [start it otherwise](#changing-state): an agent
misled by a log or a mail has no tool that changes anything on Odoo.sh.

## Arguments and results

### The project

The project is always an argument. The server does not read it from a git checkout: its working
directory is wherever the client started it, and a guess could point an agent at the wrong
project. A call without one is rejected.

### Limits

A list holds at most `limit` items, and `truncated` is true when there were more. A `limit` over
the most a tool returns is lowered to it, and one below 1 is an error. The `lines` of `read_log`
and the `timeout` of `wait_for_build` follow the same rule.

### Untrusted text

Branch names, commit messages and author names are written by other people. The server returns
them in the fields of a result only, never in a sentence of its own, and a client should treat
them as data, not as instructions. An audit log's entries are in `untrusted_entries` and a
project's members in `untrusted_members`, as a build's logs and mails are in `untrusted_` fields:
each on one line, without control characters and within a size.

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

## Troubleshooting

A tool's error says what happened and, when there is one, what the agent or you should do next.

| Error | What to do |
| --- | --- |
| No session | Run `osh auth login` in a terminal. The next call uses it, with no restart. |
| An expired session, or one Odoo.sh rejects | The same. Sessions are never refreshed. |
| An expired session that comes from `ODOUCHE_SESSION` | Restart the server with a current value, or without the variable to use the one `osh auth login` stores. A login is not read while the variable is set. |
| No usable keyring | Install a [Secret Service provider](security.md#where-the-session-is-stored), or restart the server with `ODOUCHE_SESSION` set. A locked keyring is unlocked in its own dialog. |
| Odoo.sh changed shape | Odoo.sh has no public API, and an answer no longer has the shape odouche reads. Upgrade to the latest release, and [report it](https://github.com/avanserv/odouche/issues) with the request and the field the error names if it remains. |
| A tool is missing | `change_branch_settings`, `change_project_settings` and `rebuild_branch` exist only with [`--allow-changes`](#changing-state). |
| `Extra inputs are not permitted` | A tool that changes state was given an argument it does not take, and nothing was sent. `change_project_settings` takes no IP allow list, public access or session lifetime: change those with `osh projects settings set`. |

The server is built on the [`odouche` library](library.md) and never talks to Odoo.sh directly.
