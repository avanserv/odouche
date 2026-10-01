# odouche

An unofficial toolkit for working with [Odoo.sh](https://www.odoo.sh) from your development
environment.

!!! warning "Unofficial, and pre-alpha"

    This project is not affiliated with, endorsed by, or supported by Odoo S.A. Odoo.sh has no
    public API: odouche talks to what the Odoo.sh web interface uses, which can change without
    notice. It acts with your own Odoo.sh access and nothing more, and staying within your
    agreement with Odoo is your responsibility. See [Unofficial status](unofficial.md).

    The three packages install today, but the Odoo.sh client itself is not implemented yet. These
    pages describe what each package is for; they will describe how to use it as the features land.

## Three packages, one library

| Package | What it is |
| --- | --- |
| [`odouche`](library.md) | A Python library: the client for Odoo.sh, usable in your own tools. |
| [`odouche-cli`](cli.md) | The `osh` command, in the spirit of `gcloud`, `aws` and `scw`. |
| [`odouche-mcp`](mcp.md) | A Model Context Protocol server, for development agents. |

The command-line tool and the MCP server are both built on the library and only on its public
interface, so anything they can do, your own code can do too.

## Credentials

odouche never sees, stores or logs your password or your GitHub token. The
[security model](security.md) says what it does keep, where, and for how long.
