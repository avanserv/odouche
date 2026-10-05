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
git push && osh builds watch
osh builds watch 1234 --timeout 600
```

- All work on a branch of the [project](#project-and-branch). A branch the project does not have
  exits 4.
- As JSON all give the whole [`Build`](reference.md) model: `show` one object, `list` an array,
  `watch` one object per line.
- `list` shows the branch's latest builds, newest first: the number, the status, the result, the
  short commit hash, the first line of the commit message and how long ago the build started.
- `--limit` is the most builds to list, 4 by default and at least 1. Odoo.sh has only been seen
  to answer up to four, whatever is asked: older builds are out of reach.
- `show` shows one build with its commit, its author and the address of its database: the
  branch's latest, or the one whose number is given. A number that is not among the branch's
  latest builds exits 4, and so does a branch that has no build.
- `list` and `show` exit 0 whatever the build's result: a failed build is shown, not reported as
  a failure.
- A status or a result `osh` does not know is shown as Odoo.sh names it.
- On a terminal the result is coloured, and it is always written out.
- A table shows times as how long ago they were.

`watch` follows one build until it finishes and exits with its result: 0 for a success, and one
of 20 to 23 of the [exit codes](#exit-codes) otherwise.

- It watches the build whose number is given, or the build of the commit you just pushed. When
  the checkout is of the project's repository and on the branch, however the two were named, it
  waits for a build of the checkout's HEAD to be listed, asking every 3 seconds, and watches that
  one.
- `--commit` waits for another commit of the branch, given as the first 7 to 64 digits of its
  hash, also when the branch is not the one checked out.
- `--no-wait` watches the branch's latest build, whatever its commit, and so does a run with
  no `--commit` on another project or branch than the checkout's, or one where HEAD cannot be
  read.
- The wait for a commit's build lasts two minutes at most, then exits 23: push the commit, or use
  `--no-wait`.
- `--timeout` is the longest the whole command waits, in seconds: 1800 by default and at least 1.
- The changes go to stderr: one line kept up to date when stderr is a terminal, with how long the
  build has run, and one line per change otherwise. The last line, on stdout, is the result and
  the address of the build's database.
- As JSON, stdout is one `Build` per change and nothing else, and the result line goes to stderr.
- A build that was dropped after it finished exits with the result it had, and is said to have
  been replaced by a newer build. A dropped build has no address.
- Ctrl+C exits 130 and leaves the build running: watching changes nothing on Odoo.sh.

## Logs

```bash
osh logs
osh logs --follow
osh logs --build 1234 --kind pip --tail 20
osh logs --kinds
osh logs --all | grep ERROR
```

- `logs` prints the end of one log of a build of a branch of the
  [project](#project-and-branch): the branch's latest build, or the one `--build` numbers. A
  number that is not among the branch's latest builds exits 4, and so does a branch with no build.
- `--kind` names the log. The default is `install` when the build has it, where a development
  build installs the modules and runs their tests, and `odoo` otherwise, as on a staging build.
  A log the build does not have exits 4, and the message names the ones it has.
- `--kinds` lists the logs the build has instead: the kind, what Odoo.sh calls the log, its size
  and how long ago it was last written to. A kind `osh` does not know is `unknown`, and `--kind`
  takes its name. As JSON it is the whole [`Log`](reference.md) model. A build that waits for a
  worker has no log yet.
- `--tail` is how many of the last lines are printed, 100 by default and at least 1. They are
  taken from the log's last mebibyte, so a large tail can print fewer. `--all` prints the whole
  log.
- `--follow`, or `-f`, prints the tail and then each new line as it is written, asking Odoo.sh
  every second, until Ctrl+C, which exits 130. With `--all` it starts at the first line.
- `--timeout` is the longest a follow lasts, in seconds and at least 1. Then the command exits 8.
  Without it a follow has no limit.
- A log is untrusted text. On a terminal the escape sequences and control characters are removed
  from each line, tabs kept, so a line cannot clear the screen or set the window's title. When
  stdout is a pipe or a file the lines are written as they are. `--strip` and `--no-strip` force
  one or the other.
- A line longer than 64 KiB is cut, and bytes that are not UTF-8 are replaced. A character
  stdout cannot encode is written as its escape, such as `\u2192`.
- As JSON each line is one [`LogLine`](reference.md), with the control characters escaped, so
  `--strip` has no effect.
- Each line is flushed as it is printed. When the pipe it is written to closes, as under
  `osh logs | head`, the command ends with nothing on stderr and exits 141.
- `--kinds` goes with none of the options that print a log, `--all` not with `--tail`, and
  `--timeout` only with `--follow`: the command exits 2.
- Nothing of a log is written to stderr, with `--debug` or without.

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
  space, so a commit message cannot drive the terminal. JSON has them escaped. The lines of
  [`osh logs`](#logs) keep them when stdout is not a terminal.
- An empty result is `[]` as JSON, and one line on stderr as a table. Both exit 0.

## Exit codes

A command that fails prints one or two lines on stderr, what happened and what to do, and nothing
on stdout. `osh builds watch` also exits non-zero for a build that did not succeed, with the
result line on stdout, or on stderr as JSON. `osh logs` can fail after lines went to stdout, at a
follow's timeout (8) or when a request fails (7), and a closed pipe (141) writes nothing to
stderr. Scripts can branch on the exit code:

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
| 8 | A followed log or a login reached its timeout. |
| 9 | Refused, and nothing was changed: a read-only run, or a branch in a stage `osh` does not change. |
| 10 | A change was sent and Odoo.sh did not confirm it. Look at Odoo.sh before trying again. |
| 11 | No usable keyring to store the session in. |
| 12 | The login ended without a session. |
| 13 | Any other error from the library. |
| 20 | `osh builds watch`: the build failed. `osh logs` is the next step. |
| 21 | `osh builds watch`: the build finished with warnings. |
| 22 | `osh builds watch`: the build ended without a result. It was dropped for a newer build, killed or skipped, or its result is one `osh` does not know. |
| 23 | `osh builds watch`: the build had not finished, or had not appeared, at the timeout. |
| 24 to 29 | Reserved for the result of a build. |
| 130 | Interrupted with Ctrl+C. |
| 141 | Stdout is a pipe and its reader, such as `head`, closed it. Nothing is written to stderr. |

`--debug`, or `OSH_DEBUG=1`, adds the traceback on stderr. It shows no local variables, and a
session supplied through `ODOUCHE_SESSION` is masked in it.
