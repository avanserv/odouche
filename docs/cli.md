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
