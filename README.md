# odouche

[![CI](https://github.com/avanserv/odouche/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/avanserv/odouche/actions/workflows/ci.yml?query=branch%3Amain)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

An unofficial toolkit for working with [Odoo.sh](https://www.odoo.sh) from your development
environment: list branches, watch builds, stream logs, from a script, a terminal or an agent.

> **Unofficial.** This project is not affiliated with, endorsed by, or supported by Odoo S.A.
> Odoo.sh has no public API: odouche talks to what the Odoo.sh web interface uses, which can change
> without notice.
>
> **Pre-alpha.** The three packages install, and the library logs in, lists projects, branches and builds, watches a build, reads build logs and triggers a rebuild. Nothing else is
> implemented yet.

## Packages

| Package | What it is |
| --- | --- |
| [`odouche`](packages/odouche) | A Python library: the client for Odoo.sh, usable in your own tools. |
| [`odouche-cli`](packages/odouche-cli) | The `osh` command, in the spirit of `gcloud`, `aws` and `scw`. |
| [`odouche-mcp`](packages/odouche-mcp) | A Model Context Protocol server, for development agents. |

The command-line tool and the MCP server are built on the library, and only on its public
interface.

## Credentials

odouche never sees, stores or logs your password or your GitHub token. The
[security model](docs/security.md) says what it does keep, where, and for how long.

## Development

Requires [uv](https://docs.astral.sh/uv/) and `make`.

```bash
make install   # install the workspace and the git hooks
make check     # format, lint, types, dependencies, dead code, tests with coverage, docs
make help      # everything else
```

[CONTRIBUTING.md](CONTRIBUTING.md) has the conventions, and [SECURITY.md](SECURITY.md) how to
report a vulnerability.

## License

[MIT](LICENSE)
