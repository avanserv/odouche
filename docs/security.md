# Security

odouche acts on your Odoo.sh projects with your access, so what it does with that access is a
design constraint rather than a guideline.

!!! note "Logging in is in the library only"

    The `osh auth` commands are not implemented yet. This page states the model the implementation
    is held to.

## What odouche holds

- Your **password** and your **GitHub token** are never seen, stored or logged. You sign in through
  a browser, with GitHub, as you do on Odoo.sh itself.
- Only the resulting **Odoo.sh session** is kept between runs, in your operating system's keyring.
  It is never written to a plain-text file, a configuration file or a cache.
- In headless use, such as CI, the session is read from the environment and kept in memory only.

## How you sign in

odouche opens a browser window of its own, in which you sign in to Odoo.sh with GitHub.

- The browser is a Chromium-family one already on your machine (Chrome, Chromium, Edge, Brave).
  odouche does not download one.
- The window uses a temporary profile that is deleted when the login ends, so you sign in to
  GitHub each time and nothing from that sign-in is kept.
- odouche asks the browser for one thing, the cookies of `www.odoo.sh`. It does not read what the
  pages show or the cookies of any other site, GitHub included.
- The session is kept only after it has answered one request to Odoo.sh.

With another browser, on Windows, or with no display (over SSH, in a container), sign in to
Odoo.sh in your own browser and paste the `session_id` cookie into a prompt that does not echo it.

The profile is deleted when the login is interrupted or the program is terminated, too. A program
that is killed outright cannot delete it. If the profile cannot be deleted, the login fails, the
session is not kept and the error names the directory to delete.

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

The entry is named `session`, under the service `odouche`, so you can find it and delete it by
hand.

When none of the three is available, odouche does not keep the session. It says so and names the
two ways out: install a Secret Service provider, or supply the session through the environment. It
never falls back to a file, and never prints the session for you to export.

The environment variable is `ODOUCHE_SESSION`. When it is set, the session in the keyring is
neither read nor deleted, and the one from the environment is never stored.

## How long a session lasts

- Odoo.sh decides. If Odoo.sh says a session is no longer valid, odouche discards it and asks you
  to sign in again. Sessions are never refreshed or extended.
- A client-side maximum age of 30 days applies on top of that, counted from the login and never
  extended by use.

## What never leaves

Session values do not appear in logs, exceptions, object representations, command output or MCP
tool results.

## The MCP server

The server is read-only by default. Tools that change state on Odoo.sh are opt-in, and every tool
documents what it does and what it can touch.

## Reporting a vulnerability

Please report vulnerabilities privately, through
[GitHub's private vulnerability reporting](https://github.com/avanserv/odouche/security/advisories/new),
rather than in a public issue.
