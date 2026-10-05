# odouche-mcp

An unofficial [Model Context Protocol](https://modelcontextprotocol.io) server for
[Odoo.sh](https://www.odoo.sh), so development agents can work with your projects. Built on the
[`odouche`](https://pypi.org/project/odouche/) library.

> This project is not affiliated with, endorsed by, or supported by Odoo S.A. Odoo.sh has no public
> API; this server talks to what the Odoo.sh web interface uses, which can change without notice.
> It acts with your own Odoo.sh access and nothing more, and staying within your agreement with
> Odoo is your responsibility. See [Unofficial status](https://avanserv.github.io/odouche/unofficial/).

**Status: pre-alpha.** The server reports its session, lists projects, branches and builds, and reads one
build. It changes nothing on Odoo.sh unless it is started with `--allow-changes`, which adds a tool that
starts a rebuild.

```bash
uvx odouche-mcp
```

Documentation: <https://avanserv.github.io/odouche/>
