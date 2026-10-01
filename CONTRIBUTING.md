# Contributing

## Setup

You need [uv](https://docs.astral.sh/uv/) and `make`. uv installs the right Python for you.

```bash
make install
```

That installs the three packages in editable mode with the development tools, and the git hooks.
To use the commit message template as well:

```bash
git config commit.template .gitmessage
```

## The gates

```bash
make check
```

runs everything CI runs: format and lint (ruff), type check (basedpyright), dependency
declarations (deptry), dead code (vulture), the tests with coverage (pytest), and the documentation
build (zensical). `make help` lists the individual targets, and `make format` and `make lint` apply
fixes where `make check` only reports.

The git hooks run the same checks on the files you commit, plus a few that only make sense there:
secrets (gitleaks), spelling (codespell), Markdown (markdownlint) and the workflow audits
(actionlint, zizmor). `make hooks` runs all of them over the whole tree.

## How the repository is laid out

A uv workspace with three packages under `packages/`: `odouche` (the library), `odouche-cli` (the
`osh` command) and `odouche-mcp` (the MCP server). Two rules hold between them:

- The two frontends depend on the library, and only on its public interface. They never talk to
  Odoo.sh themselves and never import each other.
- A capability is added to the library first, then surfaced in a frontend.

`make deps` is what enforces the first: each package is checked against its own manifest, so a
frontend importing something it does not declare fails. For the same reason a dependency is
declared in the same change as the code that imports it, never ahead of it.

## Tests

Tests never contact the real Odoo.sh. Upstream responses are mocked or replayed from fixtures, and
a fixture is scrubbed of session values and real project data before it is committed.

Fixtures live in `packages/<package>/tests/fixtures/` and are written by hand from a browser
capture, which is never committed.

- Session values: write `session_id=REDACTED`. gitleaks fails on a real one, in any file.
- E-mail addresses: use `example.com`. The test suite fails on any other domain in a fixture.
- Nothing checks the rest, so scrub by hand: project names, repository names, commit authors and
  messages, build hostnames.

## Commits and pull requests

Commits follow [Conventional Commits](https://www.conventionalcommits.org):
`<type>(<scope>): Summary`, with the body saying why the change exists. `.gitmessage` has the
details.

Pull requests are squash-merged, so **the pull request title is the commit**. CI checks that it is
a conventional one.

- `feat` bumps the minor version and `fix` the patch.
- `feat!`, or a `BREAKING CHANGE:` footer, is a breaking change: a minor bump while the version is
  below 1.0, a major one after.
- Everything else (`docs`, `chore`, `refactor`, `test`, `ci`, `build`, ...) bumps nothing.

## Releases

Nobody edits a version. [Release Please](https://github.com/googleapis/release-please) reads the
commits on `main` and keeps a release pull request open with the next version and the changelog.
The three packages are versioned together and always released together.

Merging the release pull request tags the release and publishes the three packages to PyPI, using
[trusted publishing](https://docs.pypi.org/trusted-publishers/): no token is stored anywhere.

Two things to know before merging one:

- Wait for the `chore: sync uv.lock with the release version` commit to land on the release branch.
  Release Please does not know about `uv.lock`; the Release workflow adds that commit.
- CI does not start by itself on the release pull request, because GitHub starts no workflow for
  what a workflow's own token pushes. **Close and reopen the pull request** to run it.

## Security

See [SECURITY.md](SECURITY.md) for how to report a vulnerability, and
[docs/security.md](docs/security.md) for the constraints every change is held to.
