# odouche-cli

`osh`, an unofficial command-line interface for [Odoo.sh](https://www.odoo.sh), in the spirit of
`gcloud`, `aws` and `scw`. Built on the [`odouche`](https://pypi.org/project/odouche/) library.

> This project is not affiliated with, endorsed by, or supported by Odoo S.A. Odoo.sh has no public
> API; `osh` talks to what the Odoo.sh web interface uses, which can change without notice. It acts
> with your own Odoo.sh access and nothing more, and staying within your agreement with Odoo is
> your responsibility. See [Unofficial status](https://avanserv.github.io/odouche/unofficial/).

**Status: pre-alpha.** `osh auth` logs in to Odoo.sh, logs out and shows the session in use, `osh projects list` and `osh branches list` list your projects and their branches, `osh builds list`, `osh builds show` and `osh builds watch` list, show and watch a branch's builds, `osh builds rebuild` starts a new one, and `osh logs` prints and follows a build's log; no other command exists yet.

```bash
uv tool install odouche-cli
osh --help
```

Documentation: <https://avanserv.github.io/odouche/>
