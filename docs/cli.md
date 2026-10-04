# CLI

`osh` is a command-line interface for Odoo.sh, in the spirit of `gcloud`, `aws` and `scw`.

```bash
uv tool install odouche-cli
```

!!! note "Not implemented yet"

    The command installs and reports its version. No Odoo.sh commands exist yet; this page will
    document them as they land.

```bash
osh --version
osh --help
```

`osh` is built on the [`odouche` library](library.md) and adds nothing of its own beyond
presentation: every command is a call into the library, rendered for a terminal.

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
