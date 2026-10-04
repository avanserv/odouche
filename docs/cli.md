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

## Output

`--format table` (the default) or `--format json`, given before the command. Only the result is
written to stdout, so `osh --format json ... | jq` receives nothing else.

- JSON keys are the attribute names of the library's models in the [reference](reference.md).
  Datetimes are ISO 8601 with an offset. A stream is one object per line.
- A table has no colour and no box drawing when stdout is not a terminal or `NO_COLOR` is set.
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
