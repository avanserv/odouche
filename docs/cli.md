# CLI

`osh` is a command-line interface for Odoo.sh, in the spirit of `gcloud`, `aws` and `scw`.

```bash
uv tool install odouche-cli
```

```bash
osh --version
osh --help
```

`osh` is built on the [`odouche` library](library.md) and adds nothing of its own beyond
presentation: every command is a call into the library, rendered for a terminal.

## Signing in

```bash
osh auth login
osh auth status
osh auth logout
```

- `login` opens a browser for you to sign in to Odoo.sh with GitHub, stores the session in the
  keyring and names the account. Where no browser can be launched it asks for the `session_id`
  cookie in a prompt that does not echo it. [Security](security.md) has what is kept and where.
- `status` shows where the session comes from, how long ago it was stored and when it expires,
  without asking Odoo.sh. It exits 3 when there is no usable session, so a script can test for
  one. `status --check` asks Odoo.sh whether it still accepts the session, and adds the user.
- `logout` removes the session from the keyring and says whether Odoo.sh ended it. With nothing
  to log out of it exits 0.
- No option takes a session: arguments show in the process list and in the shell history. With
  `ODOUCHE_SESSION` set, that session is the one in use: `login` still stores the one it gets,
  and `logout` leaves the variable for you to unset.

## Projects

```bash
osh projects list
```

- `list` shows the projects the session's user can reach: the name, the GitHub repository and
  the address of the project's page. As JSON it is the whole
  [`Project`](reference.md) model.

## Branches

```bash
osh branches list
osh branches list --stage staging --stage production
```

- `list` shows the branches of the [project](#project-and-branch) with their stage: production
  first, then staging, then development, each sorted by name. As JSON it is the whole
  [`Branch`](reference.md) model, in the same order.
- `--stage` keeps one stage and can be given more than once. A value that is not a stage exits 2.
- A stage `osh` does not know is shown as Odoo.sh names it, after the others. `--stage unknown`
  lists those.
- In the table, `*` marks the branch checked out locally, when the project comes from the
  checkout.

## Builds

```bash
osh builds list
osh builds list --branch staging --limit 2
osh builds show
osh builds show 1234
```

- Both work on a branch of the [project](#project-and-branch). A branch the project does not have
  exits 4.
- As JSON both give the whole [`Build`](reference.md) model: `show` one object, `list` an array.
- `list` shows the branch's latest builds, newest first: the number, the status, the result, the
  short commit hash, the first line of the commit message and how long ago the build started.
- `--limit` is the most builds to list, 4 by default and at least 1. Odoo.sh has only been seen
  to answer up to four, whatever is asked: older builds are out of reach.
- `show` shows one build with its commit, its author and the address of its database: the
  branch's latest, or the one whose number is given. A number that is not among the branch's
  latest builds exits 4, and so does a branch that has no build.
- Both exit 0 whatever the build's result: a failed build is shown, not reported as a failure.
- A status or a result `osh` does not know is shown as Odoo.sh names it.
- On a terminal the result is coloured, and it is always written out.
- A table shows times as how long ago they were.

## Project and branch

A command that works on a project or a branch takes them from the first of these that gives a
value:

| Order | Project | Branch |
| --- | --- | --- |
| 1 | `--project` | `--branch` |
| 2 | `OSH_PROJECT` | `OSH_BRANCH` |
| 3 | The git checkout's remote, when it is a GitHub repository | The git checkout's current branch |

- The project is given by its name, as `osh projects list` shows it.
- The remote is the upstream of the current branch, and `origin` otherwise. A detached HEAD
  gives no branch.
- A repository that several of your projects build is never guessed between: the command exits 2
  and lists them. One that none of them builds exits 4.
- With no source giving a value, or an empty `--project` or `--branch`, the command exits 2.
- `--debug` says on stderr which source was used.

## Output

`--format table` (the default) or `--format json`, given before the command. Only the result is
written to stdout, so `osh --format json ... | jq` receives nothing else.

- JSON keys are the attribute names of the library's models in the [reference](reference.md).
  Datetimes are ISO 8601 with an offset. A stream is one object per line.
- A table has no colour and no box drawing when stdout is not a terminal or `NO_COLOR` is set.
- A table has the control characters removed from every cell, and a tab or a line break made a
  space, so a commit message cannot drive the terminal. JSON has them escaped.
- An empty result is `[]` as JSON, and one line on stderr as a table. Both exit 0.

## Exit codes

A command that fails prints one or two lines on stderr, what happened and what to do, and nothing
on stdout. Scripts can branch on the exit code:

| Code | Meaning |
| --- | --- |
| 0 | Success. |
| 1 | Unexpected error, which is a bug to report, or a prompt that was declined. |
| 2 | Usage error: an unknown option, a missing argument. |
| 3 | No session, or an expired one. Run `osh auth login`. |
| 4 | The project, branch, build or log is not one the logged-in user can reach. |
| 5 | The session is not allowed to do this. |
| 6 | Odoo.sh answered in a shape `osh` does not read. Please report it. |
| 7 | Odoo.sh could not be reached, or answered with a server error. |
| 8 | A watch, a followed log or a login reached its timeout. |
| 9 | Refused, and nothing was changed: a read-only run, or a branch in a stage `osh` does not change. |
| 10 | A change was sent and Odoo.sh did not confirm it. Look at Odoo.sh before trying again. |
| 11 | No usable keyring to store the session in. |
| 12 | The login ended without a session. |
| 13 | Any other error from the library. |
| 20 to 29 | Reserved for the result of a build. |
| 130 | Interrupted with Ctrl+C. |

`--debug`, or `OSH_DEBUG=1`, adds the traceback on stderr. It shows no local variables, and a
session supplied through `ODOUCHE_SESSION` is masked in it.
