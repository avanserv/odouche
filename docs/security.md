# Security

odouche acts on your Odoo.sh projects with your access, so what it does with that access is a
design constraint rather than a guideline.

## What odouche holds

- Your **password** and your **GitHub token** are never seen, stored or logged. You sign in through
  a browser, with GitHub, as you do on Odoo.sh itself.
- Only the resulting **Odoo.sh session** is kept between runs, in your operating system's keyring.
  It is never written to a plain-text file, a configuration file or a cache.
- In headless use, such as CI, the session is read from the environment and kept in memory only.

## How you sign in

`osh auth login` opens a browser window of its own, in which you sign in to Odoo.sh with GitHub.

- The browser is a Chromium-family one already on your machine (Chrome, Chromium, Edge, Brave).
  odouche does not download one.
- The window uses a temporary profile that is deleted when the login ends, so you sign in to
  GitHub each time and nothing from that sign-in is kept.
- odouche asks the browser for one thing, the cookies of `www.odoo.sh`. It does not read what the
  pages show or the cookies of any other site, GitHub included.
- The session is kept only after it has answered one request to Odoo.sh.

With another browser, on Windows, or with no display (over SSH, in a container), sign in to
Odoo.sh in your own browser and paste the `session_id` cookie into a prompt that does not echo it.

The browser is one launched for the login, not the one you use every day: that one's cookie store
holds your session on every other site. For the same reason there is no browser extension, no
profile kept between logins and no debugging port, which any program on the machine could open.

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
`keyrings.alt`. odouche picks among the three itself, so a keyring configured or installed
elsewhere on the machine cannot become where the session goes.

`osh auth logout` ends the session on Odoo.sh and deletes the entry. It is named `session`, under
the service `odouche`, so you can also find it and delete it by hand.

When none of the three is available, odouche does not keep the session. It says so and names the
two ways out: install a Secret Service provider, or supply the session through the environment. It
never falls back to a file, and never prints the session for you to export.

A locked keyring shows its own dialog, and its password never goes through odouche. A dialog left
unanswered ends with an error: after ten seconds, or after the login's timeout during a login.

The environment variable is `ODOUCHE_SESSION`. When it is set, the session in the keyring is
neither read nor deleted, and the one from the environment is never stored.

## How long a session lasts

- Odoo.sh decides. If Odoo.sh says a session is no longer valid, odouche discards it and asks you
  to sign in again. Sessions are never refreshed or extended.
- A client-side maximum age of 30 days applies on top of that, counted from the login and never
  extended by use. A session deleted for its age is not ended on Odoo.sh.
- Logging out ends the stored session on Odoo.sh and deletes it from the keyring. It is deleted
  even when Odoo.sh cannot be reached. A session from the environment is neither ended nor deleted.

## What never leaves

Session values do not appear in logs, exceptions, object representations, command output or MCP
tool results.

## Build logs

Odoo.sh serves build logs from its worker hosts, which take a project's access token and not the
session.

- The session is sent to `www.odoo.sh` only, never to a worker.
- The token is asked from Odoo.sh for each call and kept in memory for that call. It is never
  stored, logged or shown.
- It is sent over HTTPS to the worker Odoo.sh names, and only when that is a host directly under
  `odoo.com`. Odoo.sh takes it in the address of the request.
- Log content is untrusted. It is whatever a process printed, which can include terminal escape
  sequences and your instance's own secrets. The library returns it unchanged and never writes it
  to its own log.

## What odouche can change

One call changes something on Odoo.sh: a rebuild, which starts a new build of a development or a
staging branch. Every other call only reads.

- The request is sent once and never repeated.
- A client opened read-only refuses it before anything is sent.
- The library asks for no confirmation: the tool that calls it does.

[State-changing operations](library.md#state-changing-operations) has the details.

## The MCP server

The server is read-only by default. Tools that change state on Odoo.sh are opt-in, and every tool
documents what it does and what it can touch.

## Reporting a vulnerability

Please report vulnerabilities privately, through
[GitHub's private vulnerability reporting](https://github.com/avanserv/odouche/security/advisories/new),
rather than in a public issue.
