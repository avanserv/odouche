# Security

odouche acts on your Odoo.sh projects with your access, so what it does with that access is a
design constraint rather than a guideline.

## What odouche holds

- When you sign in, your **password** and your **GitHub token** are never seen, stored or logged.
  You sign in through a browser, with GitHub, as you do on Odoo.sh itself.
- Only the resulting **Odoo.sh session** is kept between runs, in your operating system's keyring.
  It is never written to a plain-text file, a configuration file or a cache.
- In headless use, such as CI, the session is read from the environment and kept in memory only.
- Some of Odoo.sh's answers carry a token or a code: a project's access token, the GitHub token a
  project's admin set for commit statuses, the subscription and enterprise codes. odouche drops
  each one as the answer arrives, before reading anything else, and never stores, logs, shows or
  returns it. Two are read, and each is kept in memory for the one call only: the project's
  access token, which opens a build's logs and mails, and the token of the redirect Odoo.sh
  answers for a backup's file, which the download sends back to fetch the file.

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

## Build logs and mails

Odoo.sh serves build logs, and the mails a development or a staging build caught, from its worker
hosts, which take a project's access token and not the session.

- The session is sent to `www.odoo.sh` only, never to a worker.
- The token is asked from Odoo.sh for each call and kept in memory for that call. It is never
  stored, logged or shown.
- It is sent over HTTPS to the worker Odoo.sh names, and only when that is a host directly under
  `odoo.com`. Odoo.sh takes it in the address of a log's request, and in the body of a mail's.
- The worker's own address of a mail's HTML and of its pop-out carry the token: odouche never
  asks for them, builds them or prints them.
- Log content is untrusted. It is whatever a process printed, which can include terminal escape
  sequences and your instance's own secrets. The library returns it unchanged and never writes it
  to its own log.
- Mail content is untrusted too: the build's code or its data wrote it. The library turns an HTML
  body into text. It never renders it, follows a link of it, loads an image or writes it to its own
  log. A mail over 16 MiB is not read, nor is a list of mails over 16 MiB. `osh` strips a mail of
  escape sequences, control characters and bidirectional controls before printing it, on a
  terminal or not.
- An agent that runs `osh` through a shell reads that stripped text without the marking the MCP
  server gives it, which says it is not to be followed.

## A shell on a build

`osh ssh` hands over to your own `ssh`: the `osh` process becomes it.

- odouche reads, generates and uploads no SSH key. `ssh` authenticates with your configuration and
  your agent, against the keys registered on your Odoo.sh account.
- The user and the host come from Odoo.sh, so each is checked before it is an argument of `ssh`:
  the user is a number and the host is under `odoo.com`, with no label starting with a dash.
- `ODOUCHE_SESSION` is removed from the environment `ssh` gets.
- What you give after the options of `osh ssh` is given to `ssh` as it is.
- Before that, `osh` runs `true` on the build with the same `ssh`, in batch mode and with no
  input, to learn whether it gets in. That try checks no host key and records none, runs no
  command of your configuration and forwards no agent, port or display: it proves only that the
  address gets through. The `ssh` that follows checks the host key as usual.
- `osh` reads only the try's stderr: to tell a refusal of your keys, which is not the address,
  and to quote its last line.
- When it does not get in, `osh ssh` asks before allowing your address, unless `--yes` is given.
  Odoo.sh takes the address from the request, so odouche asks no other service for it. Behind a
  proxy set in the environment, the proxy's address is the one allowed.
- The MCP server has no such tool, with or without `--allow-changes`.

## A build's panels

`osh builds open` prints the URL of a build's monitor, shell or editor, and with `--open` hands it
to your default browser through Python's `webbrowser`.

- The URL holds no token and no session. It keeps only the host of the build's `url`, checked to
  be a bare host under `odoo.com`, or is `www.odoo.sh` with the quoted names of the project and
  the branch: no path, query or user part of an answer reaches it.
- The browser signs in to Odoo.sh on its own, with its own login: odouche passes it nothing else.
- `ODOUCHE_SESSION` is removed from the environment the browser gets.
- The MCP server has no such tool: an agent has no browser to open a panel in.

## What odouche can change

Three calls change something on Odoo.sh. Every other call only reads.

- A rebuild starts a new build of a development or a staging branch.
- A backup is taken of a staging or a production branch's latest build, and Odoo.sh keeps it for
  three days.
- Allowing an IP lets the address of the machine that sends it connect to the builds with `ssh`
  for one hour. The request names a branch, and the rule was seen to open other branches of the
  project too ([Upstream reference](upstream.md#allow-an-ip)).

For each of them:

- Each request is sent once and never repeated.
- A client opened read-only refuses them before anything is sent.
- Allowing an IP allows only the address the request comes from: odouche sends no address, so it
  cannot open a build to anyone else. The rule expires by itself, and odouche never removes one.
- The library asks for no confirmation: the tool that calls it does.

[State-changing operations](library.md#state-changing-operations) has the details.

## The MCP server

The server is read-only by default. Tools that change state on Odoo.sh are opt-in, and every tool
documents what it does and what it can touch. The one such tool, a rebuild, is registered only when
the server is started with [`--allow-changes`](mcp.md#changing-state), and each call of it writes a
line to the server's stderr.

The tools that read a build's log and the mails it caught put text the build wrote into an agent's
context: `read_log`, `list_mails` and `read_mail`. It is
[labelled as untrusted and not masked](mcp.md#build-logs-and-mails): a log or a mail can hold an
instruction meant for the agent, or a secret of the instance.

## Reporting a vulnerability

Please report vulnerabilities privately, through
[GitHub's private vulnerability reporting](https://github.com/avanserv/odouche/security/advisories/new),
rather than in a public issue.
