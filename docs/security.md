# Security

odouche acts on your Odoo.sh projects with your access, so what it does with that access is a
design constraint rather than a guideline.

!!! note "Authentication is not implemented yet"

    This page states the model the implementation is held to. Two points are still open and are
    listed at the end.

## What odouche holds

- Your **password** and your **GitHub token** are never seen, stored or logged. You sign in through
  a browser, with GitHub, as you do on Odoo.sh itself.
- Only the resulting **Odoo.sh session** is kept between runs, in your operating system's keyring.
  It is never written to a plain-text file, a configuration file or a cache.
- In headless use, such as CI, the session is read from the environment and kept in memory only.

## How long a session lasts

- Odoo.sh decides. If Odoo.sh says a session is no longer valid, odouche discards it and asks you
  to sign in again. Sessions are never refreshed or extended.
- A client-side maximum age applies on top of that, so a session forgotten on a machine does not
  stay usable for as long as Odoo.sh would allow.

## What never leaves

Session values do not appear in logs, exceptions, object representations, command output or MCP
tool results.

## The MCP server

The server is read-only by default. Tools that change state on Odoo.sh are opt-in, and every tool
documents what it does and what it can touch.

## Open questions

- How the session is captured at the end of the browser sign-in.
- What happens when no keyring backend is available, as is common on WSL2. odouche will not fall
  back to a file silently.

## Reporting a vulnerability

Please report vulnerabilities privately, through
[GitHub's private vulnerability reporting](https://github.com/avanserv/odouche/security/advisories/new),
rather than in a public issue.
