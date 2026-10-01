# Security

odouche acts on your Odoo.sh projects with your access, so what it does with that access is a
design constraint rather than a guideline.

!!! note "Authentication is not implemented yet"

    This page states the model the implementation is held to. One point is still open and is
    listed at the end.

## What odouche holds

- Your **password** and your **GitHub token** are never seen, stored or logged. You sign in through
  a browser, with GitHub, as you do on Odoo.sh itself.
- Only the resulting **Odoo.sh session** is kept between runs, in your operating system's keyring.
  It is never written to a plain-text file, a configuration file or a cache.
- In headless use, such as CI, the session is read from the environment and kept in memory only.

## Where the session is stored

odouche accepts three keyrings and nothing else:

| Environment | Where the session goes |
| --- | --- |
| Linux desktop | Secret Service (GNOME Keyring, KeePassXC and others) |
| macOS | Keychain |
| Windows | Credential Locker |
| WSL2 | Secret Service, once a provider is installed |
| Container, CI | The environment, in memory only |

Any other keyring backend is refused with an error, including the plain-text ones from
`keyrings.alt`.

When none of the three is available, odouche does not keep the session. It says so and names the
two ways out: install a Secret Service provider, or supply the session through the environment. It
never falls back to a file, and never prints the session for you to export.

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

## Open question

How the session is captured at the end of the browser sign-in.

## Reporting a vulnerability

Please report vulnerabilities privately, through
[GitHub's private vulnerability reporting](https://github.com/avanserv/odouche/security/advisories/new),
rather than in a public issue.
