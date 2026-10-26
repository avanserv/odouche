# Manual tests

What no automated test covers, to run by hand before a release: every test mocks Odoo.sh, the
keyring, the browser and the MCP client, and `make live-check` asks only for what the library
reads.

- Each expected outcome is what the documentation and the code say, not what a run showed. A
  check that fails is a defect in one or the other.
- Results are not written here: outputs carry project names. Cite a check by its number.
- `<project>` is a project you can reach, `<dev-branch>` a development branch made to be thrown
  away, `<build>` one of its latest builds. An empty precondition means logged in, in a checkout
  of the project's repository, on `<dev-branch>`.
- Everything was written for WSL2. [Not covered](#not-covered) has the rest.

## Install and docs

In a new directory outside the repository, with no `UV_*` variable set, so that what is installed
is what PyPI serves.

| # | Precondition | Command or action | Expected | Exit |
| --- | --- | --- | --- | --- |
| I1 | | `uv tool install odouche-cli`, then `osh --version` | `osh X (odouche X)`, both the released version | 0 |
| I2 | | `osh --format json --version` | One line of JSON with `osh` and `odouche` | 0 |
| I3 | | `uvx --from odouche-cli osh --help` | The help, with the `auth`, `branches`, `builds`, `logs`, `projects` and `ssh` commands | 0 |
| I4 | | `osh`, then `osh auth`, with no argument | The help | 2 |
| I5 | | `osh --bogus` | `No such option: --bogus` on stderr | 2 |
| I6 | A new project from `uv init` | `uv add odouche`, then the first example of [Library](library.md) | It runs as written | 0 |
| I7 | | The [pinned `uvx` command](mcp.md#any-other-client) | The released version is installed, and the server waits on stdin until it is closed | - |
| I8 | `uv tool install odouche-mcp` | `odouche-mcp --help` | `usage: odouche-mcp [-h] [--allow-changes]` | 0 |
| I9 | The same | `odouche-mcp --allow` | `unrecognized arguments` on stderr | 2 |
| I10 | A project with `odouche-mcp` added | `uv run python -m odouche_mcp --help` | As I8 | 0 |
| I11 | zsh | `osh --install-completion`, then in a new shell complete a command, a subcommand and an option | Each completes. No project or branch name is offered | 0 |
| I12 | bash | The same | The same | 0 |
| I13 | | `osh --show-completion` | The script on stdout, and no file written | 0 |
| I14 | | Paste every code block of [Overview](index.md), [CLI](cli.md), [Library](library.md), [MCP server](mcp.md) and the three package READMEs | Each runs as written, with only a project and a branch of yours in place of the example's | - |
| I15 | | Read the published site | Every navigation entry opens, no internal link is dead, and the two generated references and the API reference render | - |
| I16 | | Read the setup snippets of the published [MCP server](mcp.md#setup) page and of the `odouche-mcp` README on PyPI | The pinned version is the released one | - |
| I17 | The workspace | `make docs` | The site is built into `site/` with no warning | 0 |
| I18 | The workspace | `make live-check PROJECT=<project>` | Seven steps, each `pass` or `skipped`, and a last line of counts with `0 failed` | 0 |
| I19 | The workspace | `CI=1 make live-check PROJECT=<project>` | `Refused: the live check never runs in CI.` | 2 |

## Login and session store

Search the output of every check below for the session value: it appears in none.

| # | Precondition | Command or action | Expected | Exit |
| --- | --- | --- | --- | --- |
| L1 | No Secret Service provider, `ODOUCHE_SESSION` unset | `osh auth login` | The `No usable keyring` message, naming a Secret Service provider and the environment as the two ways out. No browser opens and no prompt is shown | 11 |
| L2 | After L1 | Search the home directory and the temporary directory for the session value | No match | - |
| L3 | As L1 | `osh auth status`, then `osh projects list` | The same message | 11 |
| L4 | A provider installed, a display, a Chromium-family browser on the `PATH` | `osh auth login`, and sign in | stderr: `Checking the keyring. Unlock it if it asks.`, that a browser window is open, then `The session is stored in the keyring.` stdout: `Logged in as <user>.` | 0 |
| L5 | After L4 | `ls -d "${TMPDIR:-/tmp}"/odouche-login-*` | No such directory | - |
| L6 | As L4 | `osh auth login`, then Ctrl+C while the window is open | Nothing more on stderr, the window closes, and L5 holds | 130 |
| L7 | As L4 | `osh auth login`, then close the window by hand | `The browser was closed before the login completed.` and the hint to run `osh auth login` again. L5 holds | 12 |
| L8 | As L4 | During a login, `ps -ef` in another terminal | The session value is in no argument of the browser or of `osh` | - |
| L9 | The keyring locked | `osh projects list`, leaving the keyring's dialog unanswered | After ten seconds, `The keyring is waiting to be unlocked.` | 11 |
| L10 | After L9, the dialog still open | `osh projects list` again, then answer the dialog | No second dialog opens. The command ends as L9 or lists the projects | 11 or 0 |
| L11 | A provider, no display | `env -u DISPLAY -u WAYLAND_DISPLAY osh auth login`, and paste a valid cookie | stderr says no browser can be launched and asks for `session_id` without echoing it. Then as L4 | 0 |
| L12 | As L11 | The same, and paste a value that is not a cookie | `The pasted value is not a session_id cookie value.` Nothing is stored | 12 |
| L13 | As L11 | The same, and paste a well-formed value Odoo.sh does not know | `Odoo.sh did not accept the pasted session.` Nothing is stored | 12 |
| L14 | As L11 | The same, and press Enter on an empty prompt | The prompt is shown again | - |
| L15 | As L11 | The same, and Ctrl+C at the prompt | Nothing is stored, and no traceback | 130 |
| L16 | Logged in | `osh auth status` | Rows `Source` (`keyring`), `Stored` and `Expires` (within 30 days of the login). No request is sent | 0 |
| L17 | Logged in | `osh auth status --check` | Also `User`, `Name` and `Email`, as Odoo.sh has them | 0 |
| L18 | Logged in | `osh --format json auth status`, then with `--check` | One `SessionInfo`, then one `Identity` with it as `session`. Neither holds the session value | 0 |
| L19 | Logged out | `osh auth status` | `Not logged in.` and the hint to run `osh auth login` | 3 |
| L20 | `ODOUCHE_SESSION` set to a valid session, the keyring holding another or none | `osh projects list`, then `osh auth status` | The projects. `Source` is `environment`, `Stored` and `Expires` are `unknown`. The keyring entry is unchanged | 0 |
| L21 | As L20 | `osh auth logout` | That the session comes from `ODOUCHE_SESSION` and nothing was changed. The keyring entry is unchanged and the session still works | 0 |
| L22 | As L20, a provider | `osh auth login` | The login is stored, and stderr adds that `ODOUCHE_SESSION` is used until it is unset. stdout: `Logged in.` | 0 |
| L23 | `ODOUCHE_SESSION` set to a value that is not a cookie | `osh projects list`, then again with `--debug` | `The value of ODOUCHE_SESSION is not a session_id cookie value.` The traceback does not show the value | 3 |
| L24 | Logged in | `osh auth logout` | `The stored session was removed from the keyring and ended on Odoo.sh.` The cookie no longer works in a browser | 0 |
| L25 | Logged out | `osh auth logout` | `Not logged in.` | 0 |
| L26 | The keyring entry overwritten with other text, such as with `secret-tool store` | `osh auth logout` | `The stored session was removed from the keyring. It was not ended on Odoo.sh.` | 0 |
| L27 | Logged in, the network down | `osh auth logout` | The entry is removed, and the line says Odoo.sh could not be asked to end it and why | 0 |
| L28 | Logged in, then the session ended from the browser | `osh projects list`, twice | First `Odoo.sh rejected the session. Log in again.`, then `Not logged in.`: the entry was discarded | 3 |
| L29 | Logged in | The keyring's own tool, such as `secret-tool search service odouche` | One entry, `session`, under the service `odouche` | - |

## Read commands

| # | Precondition | Command or action | Expected | Exit |
| --- | --- | --- | --- | --- |
| R1 | | `osh projects list` | Every project of the account, as the web page lists them | 0 |
| R2 | | `osh branches list` | Production, staging, then development, each sorted by name. `*` marks `<dev-branch>` | 0 |
| R3 | | `osh branches list --stage` with `production`, `staging`, `development` and `unknown` in turn, then with two of them | Only the branches of those stages. A stage with none gives one line on stderr | 0 |
| R4 | | `osh branches list --stage bogus` | A usage error naming the four values | 2 |
| R5 | | `osh builds list`, then with `--limit 1` and `--limit 20` | Four builds at most, then one, then as many as Odoo.sh answers. Columns `ID`, `Status`, `Result`, `Commit`, `Subject`, `Age` | 0 |
| R6 | | `osh builds list --limit 0` | A usage error | 2 |
| R7 | | `osh builds show`, then `osh builds show <build>` | The latest build, then that one, with its full commit and its URL. A failed build exits 0 too | 0 |
| R8 | A directory that is no checkout | Each read command with `--project <project> --branch <dev-branch>`, then with `OSH_PROJECT` and `OSH_BRANCH` | As from the checkout, without the `*` | 0 |
| R9 | A checkout with an SSH remote, then one with an HTTPS remote | `osh --debug branches list` | The project is found, and stderr names the checkout as the source | 0 |
| R10 | A checkout, with `OSH_PROJECT` set, then with `--project` as well | `osh --debug branches list` | The variable wins over the checkout, and the option over the variable. stderr names the source | 0 |
| R11 | A directory that is no checkout, no variable | `osh branches list`, then `osh builds list --project <project>` | `No project.` then `No branch.`, each with the ways to give one | 2 |
| R12 | | `osh branches list --project ""` | `--project is empty.` | 2 |
| R13 | A checkout of a repository no project of yours builds | `osh branches list` | `No project you can reach builds <repository>.` | 4 |
| R14 | A repository that several of your projects build, if there is one | `osh branches list` | The projects are listed, with `--project` and `OSH_PROJECT` as the way to pick | 2 |
| R15 | A terminal 80 columns wide, then at full width | Each read command | No row is broken by a long subject or branch name. The result of a build is coloured | 0 |
| R16 | | Each read command piped into `cat`, then with `NO_COLOR=1` in the terminal | No colour and no box drawing | 0 |
| R17 | | Each read command with `--format json`, piped into `jq .` | It parses. Times are ISO 8601 with an offset. stderr is empty | 0 |
| R18 | A branch with no build, if there is one | `osh builds list`, then with `--format json` | `No builds.` on stderr, then `[]` | 0 |
| R19 | | `osh builds show` on that branch | `Branch <name> of <project> has no build.` | 4 |
| R20 | Logged out | Each read command | `Not logged in.` and the hint to run `osh auth login`. Nothing on stdout | 3 |
| R21 | | `osh branches list --project nope` | That the user can reach no project of that name | 4 |
| R22 | | `osh builds list --branch nope` | `Project <project> has no branch nope.` | 4 |
| R23 | | `osh builds show 1` | That build 1 is not among the latest builds of the branch | 4 |
| R24 | A project `osh projects list` shows and Odoo.sh refuses the branches of, if there is one | `osh branches list --project` with it | That the session is not allowed to do this, with no traceback | 5 |
| R25 | The network down | `osh projects list`, then again with `--debug` | `Odoo.sh could not be reached` and `Try again later.` A traceback only with `--debug` | 7 |
| R26 | A local proxy that logs its requests | `HTTPS_PROXY=<proxy> osh projects list` | The request goes through the proxy | 0 |
| R27 | The same | The same with `NO_PROXY=www.odoo.sh` | The proxy sees no request | 0 |
| R28 | A proxy that intercepts TLS with its own authority | `HTTPS_PROXY=<proxy> osh projects list`, then with `SSL_CERT_FILE` set to that authority | Refused as unreachable, then the projects | 7, then 0 |
| R29 | The same proxy | `HTTP_PROXY=<proxy> osh projects list` | The proxy sees no request | 0 |
| R30 | | `osh backups list`, then with `--branch` naming the production branch, then with `--format json` | Every branch's backups, newest first, as the Backups tab lists them. Columns `Taken (UTC)`, `Kind`, `Branch`, `Build`, `Commit`, `Size`, `Downloadable`. Only `remote` has a size and is `no`. Then that branch's alone. Then an array of `Backup` | 0 |
| R31 | | `osh backups list --branch nope` | `No backups.` on stderr | 0 |
| R32 | A branch with over 20 events in its History tab | `osh branches history`, then with `--limit 30`, then `--limit 30 --commits` | Ten events, newest first, as the History tab lists them. Columns `When`, `Kind`, `Build`, `Status`, `Result`, `By`, `Change`. Then thirty, the last ten matching the tab past its first twenty, which settles the `offset` question in [upstream](upstream.md). Then each commit in full | 0 |
| R33 | | `osh branches settings --branch <dev-branch>`, then on the production branch, then with `--format json` | One setting per line, as the branch's Settings tab shows them: `On new commit` is `new_build` on the development branch and `update` on the production one. Then one `BranchSettings`, with the library's values | 0 |
| R34 | A project whose repository has a submodule, a branch that pins an Odoo revision, and one that follows the latest. A branch pinned to a revision past its `date_expiration`, if there is one | On each branch, `osh branches revision`, then with `--build <an older build>`, then with `--format json` | The head commit as GitHub shows it, then the Odoo version and the refs, which match the branch's Settings tab under "Repository revisions", marked pinned or latest. The submodule line on stderr each time, and one `BuildRevision` as JSON. Write the answer to `/app/revision/<id>`, and the one for an expired revision, into [upstream](upstream-branches.md#revision) | 0 |

## Streams and rebuild

On `<dev-branch>` only. A staging or a production branch is never rebuilt by a test: the one
check that names production is the refusal.

| # | Precondition | Command or action | Expected | Exit |
| --- | --- | --- | --- | --- |
| S1 | A commit just pushed | `osh builds watch` | It waits for the build of that commit, shows each change within seconds of the web page, and ends on `Build <id> succeeded:` with the build's URL on stdout | 0 |
| S2 | A build in progress | `osh builds watch <build>` | That build is followed to its end | Its result |
| S3 | A commit just pushed, from a directory that is no checkout | `osh builds watch --project <project> --branch <dev-branch> --commit <sha>` | As S1 | 0 |
| S4 | A commit not pushed | `osh builds watch` | After two minutes, that the branch has no build of the commit, with `--no-wait` as the other way | 23 |
| S5 | The same | `osh builds watch --no-wait` | The branch's latest build is watched, whatever its commit | Its result |
| S6 | A build in progress | `osh builds watch --no-wait --timeout 5` | `Timed out: build <id> has not finished.` The build goes on | 23 |
| S7 | A build already finished | `osh builds watch <build>` | Its result line at once | Its result |
| S8 | A commit that fails to install | `osh builds watch` | `Build <id> failed:` with the URL, then the hint to run `osh logs` on stderr | 20 |
| S9 | A commit that logs a warning, if one can be made | `osh builds watch` | `Build <id> finished with warnings:` with the URL | 21 |
| S10 | A build in progress | `osh builds watch --no-wait`, then push a newer commit to the branch | That the build ended without a result, with `dropped` and no URL | 22 |
| S11 | | `osh builds watch 1 --commit abcdef0`, then `--no-wait --commit abcdef0`, then `--commit xyz` | That `--commit` goes with neither, then that a commit is 7 to 64 hexadecimal digits | 2 |
| S12 | A build in progress, in a terminal | `osh builds watch --no-wait` | One line on stderr, redrawn, with the status and the time run | Its result |
| S13 | A build in progress | `osh builds watch --no-wait 2>watch.txt` | One line per change in the file, and the result line on stdout | Its result |
| S14 | A build in progress | `osh --format json builds watch --no-wait` | One `Build` per line on stdout for each change, and the result line on stderr | Its result |
| S15 | A build that stays more than 60 seconds in one status | `osh builds watch --no-wait` | The next change still shows within seconds of the web page | Its result |
| S16 | A build in progress | `osh builds watch --no-wait`, with the network cut for a few seconds | The watch goes on and ends on the build's result | Its result |
| S17 | A build in progress | `osh builds watch --no-wait`, then Ctrl+C | Nothing more is printed, the terminal is left clean, and the build goes on | 130 |
| S18 | A finished build | `osh logs --kinds` | A table of `Kind`, `Name`, `Size` and `Changed` | 0 |
| S19 | The same | `osh logs`, then `osh logs --kind <name>` for each name S18 lists | The last 100 lines of the `install` log, then of each one | 0 |
| S20 | The same | `osh logs --kind nope` | That the build has no such log, with the ones it has | 4 |
| S21 | The same | `osh logs --build <build>` for an older build | That build's log | 0 |
| S22 | The same | `osh logs --tail 5`, then a `--tail` above the log's line count | Five lines, then the whole log or its last mebibyte | 0 |
| S23 | A log over a mebibyte | `osh logs --all >all.txt` | The whole log, from its first line | 0 |
| S24 | A log with colour sequences | `osh logs` in a terminal, piped into `cat -v`, then each with `--strip` and `--no-strip` | Stripped in the terminal and raw in the pipe, unless the option says otherwise | 0 |
| S25 | A finished build | `osh --format json logs --tail 5` | One `LogLine` per line | 0 |
| S26 | A long log | `osh logs --all` piped into `head -n 1` | One line, and nothing on stderr | 141 |
| S27 | | `osh logs --kinds --tail 5`, `osh logs --all --tail 5`, `osh logs --timeout 5`, `osh logs --tail 0` | That the options do not go together, then that `--tail` is at least 1 | 2 |
| S28 | A build about to start | `osh logs --follow --all >followed.txt` until the build ends, then Ctrl+C, then `osh logs --all >all.txt` | The two files are the same: no line lost or repeated | 130 |
| S29 | A build in progress | `osh logs --follow --timeout 5` | `The log was still being followed at the timeout.` | 8 |
| S30 | A build waiting for a worker | `osh logs --kinds`, then `osh logs` | `Build <id> has no log yet.` both times | 0, then 4 |
| S31 | | `osh builds rebuild`, and answer `n` | stderr names the project, the branch with its stage and the latest build, asks, then says `Nothing was sent.` `osh builds list` is unchanged | 1 |
| S32 | | `osh builds rebuild`, and answer `y` | `Build <id> was started.` on stderr, then the build as `osh builds show` shows it. `osh builds list` has it | 0 |
| S33 | | `osh builds rebuild --yes` | The same, with no question | 0 |
| S34 | | `osh builds rebuild --yes --watch` | The new build is watched as in S1 | Its result |
| S35 | | `osh builds rebuild --yes --watch --timeout 5` | `Timed out`, then that the build may still be running and how to follow it | 23 |
| S36 | | `osh builds rebuild --timeout 5` | That `--timeout` goes with `--watch` only | 2 |
| S37 | | `osh builds rebuild < /dev/null` | That the rebuild cannot be confirmed, with `--yes` as the way. `osh builds list` is unchanged | 2 |
| S38 | | `osh builds rebuild`, then Ctrl+C at the question | `osh builds list` is unchanged | 130 |
| S39 | | `osh builds rebuild --branch <production branch>` | That a branch in the production stage is not rebuilt. No summary and no question. The branch has no new build | 9 |
| S40 | A build of `<dev-branch>` in progress | `osh builds rebuild --yes` | Not known: [Upstream reference](upstream.md) has it as an open question. Write down what Odoo.sh answers | - |
| S41 | A public key registered on the account, a running build, an allowed address | `osh ssh`, then `exit 3` in the shell | A shell on the latest build of `<dev-branch>`, as `ssh <build id>@<host>` from the page gives. `ssh`'s exit code is `osh`'s | 3 |
| S42 | The same | `osh ssh --branch` with a staging branch, then with the production branch, each with `-- true` | The command runs on that build | 0 |
| S43 | The same | `osh ssh -- -v true`, then `osh ssh -- -L 8069:localhost:8069` | `ssh`'s debug lines, with no identity file named by `osh`. Then the port is forwarded | 0 |
| S44 | `ODOUCHE_SESSION` set | `osh ssh -- -o PermitLocalCommand=yes -o LocalCommand=env true` | The environment of `ssh`, with no `ODOUCHE_SESSION` in it | 0 |
| S45 | `PATH` without `ssh` | `osh ssh` | That there is no `ssh`, with the command to run | 14 |
| S46 | An address not allowed, as from a new network: no permanent rule, and no allow on any branch of the project within the hour | `osh ssh -- true`, and answer `n` | That `ssh` does not get into build `<id>` without a prompt, the question, then `Nothing was sent.` No change in the page | 1 |
| S47 | The same | `osh ssh -- true`, and answer `y` | `Odoo.sh allowed <address> for one hour`, the address the page's Allow my IP shows. A waiting line until `ssh` gets in, within ten minutes, then the command runs with no `Connection closed`. Write down what the request answered and whether another branch of the project is reachable too, in [Upstream reference](upstream.md#allow-an-ip) | 0 |
| S48 | Within the hour after S47, then over an hour after it | `osh ssh -- true`, then `osh ssh --yes -- true` | First no question and no waiting line. Then the address is allowed again with no question. The command runs each time | 0 |
| S49 | An address not allowed | `osh ssh -- true < /dev/null` | That allowing cannot be confirmed, with `--yes` and Allow my IP as the ways. Nothing is sent | 2 |

## Backups

On a staging branch, then once on the production branch: each run takes a real backup, which
Odoo.sh keeps for 3 days, or prepares a real file, which it keeps for 2 hours. Delete the files
B11 to B19 and B21 to B23 write. `<staging-branch>` is a staging branch of `<project>`.

| # | Precondition | Command or action | Expected | Exit |
| --- | --- | --- | --- | --- |
| B1 | | `osh backups create --branch <staging-branch>`, and answer `n` | stderr names the project, the branch with its stage, the latest build and the 3 days, asks, then says `Nothing was sent.` `osh backups list` is unchanged | 1 |
| B2 | | `osh backups create --branch <staging-branch> --comment "manual test"`, and answer `y` | `A backup of build <id> was asked for.`, then the `osh backups list` command to look with. About a minute later, that command lists a `manual` backup of that build | 0 |
| B3 | | `osh backups create --branch <staging-branch> --yes --wait` | No question, `Waiting for Odoo.sh to finish it.`, then the new backup as `osh backups list` shows it | 0 |
| B4 | | `osh backups create --branch <staging-branch> --yes --wait --timeout 5` | That the backup may still be coming, then that it was not finished at the timeout. `osh backups list` shows it a minute later | 8 |
| B5 | | `osh backups create --branch <staging-branch> --timeout 5` | That `--timeout` goes with `--wait` only | 2 |
| B6 | | `osh backups create --branch <staging-branch> < /dev/null` | That the backup cannot be confirmed, with `--yes` as the way. Nothing is sent | 2 |
| B7 | | `osh backups create --branch <dev-branch>` | That a branch in the development stage is not backed up. No summary and no question | 9 |
| B8 | | `osh backups create --branch <production branch> --yes --wait` | The new backup, as in B3. Record what Odoo.sh answered in [Upstream backups](upstream-backups.md) | 0 |
| B9 | | `osh backups download --branch <staging-branch>` | That `--output` or `--link` is needed. Nothing is asked of Odoo.sh | 2 |
| B10 | `x.zip` exists | `osh backups download --branch <staging-branch> --output x.zip` | That it exists and is never written over. `x.zip` is unchanged | 2 |
| B11 | A manual backup on `<staging-branch>` | `osh backups download --branch <staging-branch> --output n.zip`, and answer `y` | The summary, the question, the wait, then `Wrote n.zip`. `stat -c %a n.zip` is `600`, and `unzip -l n.zip` lists `dump.sql` and `filestore/` | 0 |
| B12 | The same | `osh backups download --branch <staging-branch> --output e.zip --exact --yes` | As B11. Record what the file holds and whether the database is neutralized in [Upstream backups](upstream-backups.md) | 0 |
| B13 | The same | `osh backups download --branch <staging-branch> --output s.zip --no-filestore --yes` | As B11, and `unzip -l s.zip` lists no `filestore/`. Record it as for B12 | 0 |
| B14 | The same | `osh backups download --branch <staging-branch> --output es.zip --exact --no-filestore --yes` | As B13 for the exact database | 0 |
| B15 | The same | `osh backups download --branch <staging-branch> --link --yes`, then open the link in a browser signed in to Odoo.sh, then in a private window | A link without `token` on stdout. The signed-in browser downloads the file; the private window does not | 0 |
| B16 | The same | `osh --debug backups download --branch <staging-branch> --output d.zip --yes 2>&1 \| grep -c token=` | `0`: no token anywhere | 1 (grep's) |
| B17 | | `osh backups download --branch <staging-branch> --new --yes --output new.zip` | One run takes a backup, waits for it, prepares its file and writes it, as B11 | 0 |
| B18 | A `remote` backup listed | `osh backups download "<its time>" --branch <production branch> --output r.zip --yes`, with the time of a `remote` backup that has no `daily` one | That it is `remote` and Odoo.sh does not let it be downloaded. No `r.zip` | 4 |
| B19 | Within 2 hours of B11 | `osh backups download "<B11's backup time>" --branch <staging-branch> --output n2.zip` | `Odoo.sh already holds this file`, no question and no wait. `cmp n.zip n2.zip` finds no difference | 0 |
| B20 | A backup whose file takes more than a few seconds | `osh backups download --branch <staging-branch> --output c.zip --yes`, and press Ctrl+C while it downloads | No `c.zip` is left | 130 |
| B21 | SSH access to the production build | `osh backups pull --output daily.sql.gz` | `Copying daily backup ...`, then `rsync` copies it. `stat -c %a daily.sql.gz` is `600`, and `zcat daily.sql.gz \| head` is SQL | 0 |
| B22 | A manual backup on `<staging-branch>` | `osh backups pull --manual "<its time>" --output manual.sql.gz` | As B21. If the file is not found, the name's time is not UTC: record it in [Upstream backups](upstream-backups.md#on-the-production-build) | 0 |
| B23 | `PATH` with `ssh` and `scp` but no `rsync` | `osh backups pull --output scp.sql.gz` | `scp` copies it. `stat -c %a scp.sql.gz` is `600` | 0 |
| B24 | | `osh backups pull --branch <staging-branch> --output x.sql.gz` | That the backups are copied from the production build. Nothing is tried | 2 |

## MCP server

In Claude Code, with the released version from PyPI and the server named `odouche`. Search every
tool result and the server's stderr for the session value: it appears in none.

| # | Precondition | Command or action | Expected | Exit |
| --- | --- | --- | --- | --- |
| M1 | | Set the server up with [`claude mcp add`](mcp.md#claude-code) as written | The client lists ten tools, and no `rebuild_branch` | - |
| M2 | | Set it up with the `.mcp.json` snippet instead | The same | - |
| M3 | Logged out | Start the client | The server starts and lists its tools | - |
| M4 | Logged out | Ask whether there is a session | `get_session`: `available` is false and `problem` says to run `osh auth login`. It is not an error | - |
| M5 | After M4, the server still up | `osh auth login` in another terminal, then ask again | `available` is true, with the identity and the seconds left. No restart | - |
| M6 | No Secret Service provider, `ODOUCHE_SESSION` unset | Ask for the projects | The error says there is no usable keyring, and that where there is none the user restarts the server with `ODOUCHE_SESSION` set. The agent stops and asks for that | - |
| M7 | The server started with an `ODOUCHE_SESSION` that Odoo.sh rejects | Ask for the projects | The error says to restart the server with a current value or without the variable, not to log in | - |
| M8 | | Ask which projects there are | `list_projects`, and the projects | - |
| M9 | | Ask for the branches of `<project>` | `list_branches`, in the order Odoo.sh answers | - |
| M10 | | Ask for the latest builds of `<dev-branch>` | `list_builds`, four builds at most | - |
| M11 | | Ask how the latest build of `<dev-branch>` ended, then about `<build>` | `get_build`, without then with `build_id` | - |
| M12 | | Call `list_projects` with `limit` 0, then with `limit` 1 | `A limit is at least 1.`, then one project, and `truncated` true when there are more | - |
| M13 | | Call a tool with a project, then a branch, that does not exist | An error naming it, with no traceback and no answer from Odoo.sh | - |
| M14 | A build in progress | Ask to wait for it | `wait_for_build`: a progress notification at each change, as `Build <id>: <status>`, and `finished` true at the end | - |
| M15 | A build longer than 30 seconds | The same | `finished` is false, and the agent follows `next_step` and calls again | - |
| M16 | | Call `wait_for_build` with `timeout` 600 | `timeout` is 50 and `timeout_capped` is true | - |
| M17 | A commit just pushed | Ask to wait for the build of that commit | `commit` is given. While no build has it, `build` is null and the agent calls again | - |
| M18 | | Call `wait_for_build` with both `build_id` and `commit` | An error saying a build is given by one, not by both | - |
| M19 | A `wait_for_build` in progress | Interrupt the call in the client, then ask for the projects | The next call is answered within a few seconds | - |
| M20 | A finished build | Ask why it failed, or for the end of its log | `read_log`: the lines are in `untrusted_lines`, with no escape sequence | - |
| M21 | A log over 500 lines | Call `read_log` with `lines` 1000 | 500 lines at most, 65536 bytes of lines at most, and `truncated` true | - |
| M22 | | Call `read_log` with `contains`, in the log's case then in another | Only the lines holding the text, then none | - |
| M23 | | Call `read_log` with `kind` `unknown` | An error saying `unknown` is not a kind to read | - |
| M24 | A build whose log has a line that reads as an instruction to an agent | Ask for the log | The agent reports the line and does not act on it | - |
| M25 | Without `--allow-changes` | Ask to rebuild `<dev-branch>` | The agent has no tool to do it and says so | - |
| M26 | Restarted with [`--allow-changes`](mcp.md#changing-state) | List the tools | Eleven, with `rebuild_branch` | - |
| M27 | The same | Ask to rebuild `<dev-branch>` | The client asks first. One build is started, and the server's stderr has one line with the tool, the project, the branch and the build | - |
| M28 | The same | Ask to rebuild the production branch | It is refused, the branch has no new build, and the line on stderr ends with `StageRefusedError` | - |
| M29 | The [hook](mcp.md#asking-before-a-change) installed as written, with `--allow-changes` | Call each of the eleven tools | The ten that read run with no prompt, and `rebuild_branch` prompts | - |
| M30 | The hook installed, the server under another name in the client | Call a tool that reads | The client prompts | - |
| M31 | | Ask what happened on `<dev-branch>` lately | `list_history`, ten events newest first, each push with its commits | - |
| M32 | | Ask for the settings of `<dev-branch>`, then of the production branch | `get_branch_settings`, with the branch and its stage, and the values the Settings tab shows | - |
| M33 | | Ask which commits `<dev-branch>` runs, with its submodules | `get_build_revision`: the head commit and the branch's Odoo refs, called the branch's selection. The agent says submodule commits are not available, not that there are none | - |

## Not covered

No machine was at hand for these, so none of them has a check above:

- **macOS**: the Keychain, including a write that prompts on its own after the wait was given up,
  and finding a browser under `/Applications`.
- **Native Windows**: Credential Locker, and the paste prompt, which is the only login there.
- **A native Linux desktop**: Secret Service inside a desktop session, where the keyring is
  unlocked at login, and a browser launched outside WSLg.
- **A snap or flatpak Chromium**, which keeps its profile elsewhere.
- **Installing with `pip` or `pipx`**: the documentation gives the uv forms only.
- **Another MCP client than Claude Code.**
- **A rebuild of a staging branch**: the library lets it through and it has never been sent.
