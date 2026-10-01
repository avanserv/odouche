# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`odouche` helps Odoo developers work with Odoo.sh from their dev environment. Odoo.sh has no
official public API; this project is an **unofficial** client for what the Odoo.sh web UI uses.

Status: the workspace, tooling and CI exist; the packages are skeletons (`osh --version`, an MCP
server with no tools, an empty library). The Odoo.sh client and authentication are not implemented.
The architecture and security sections below are the design the implementation is held to.

## Architecture

A uv workspace with three distributions under `packages/`, layered strictly one way:

| Package | Role |
| --- | --- |
| `odouche` | Python library: the API proxy for Odoo.sh (projects, branches, builds, logs). Usable on its own in third-party tools. |
| `odouche-cli` | The `osh` command, in the spirit of `gcloud` / `aws` / `scw`. |
| `odouche-mcp` | MCP server exposing the same capabilities to development agents. |

Rules that hold across packages:

- `odouche-cli` and `odouche-mcp` depend on `odouche` and only on its public API. They never talk
  to Odoo.sh directly and never import each other. `make deps` enforces this: deptry checks each
  package against its own `pyproject.toml`, so an import the package does not declare fails.
- A dependency is declared in the same change as the code that imports it, never ahead of it
  (deptry also fails on a declared dependency nothing imports).
- All knowledge of Odoo.sh endpoints, payload shapes and scraping lives in one layer inside
  `odouche`. Upstream is undocumented and can change without notice; a breakage should be fixable
  in that layer without touching the CLI or the MCP server.
- The library returns typed models, not raw upstream payloads. Rendering (tables, JSON, MCP tool
  results) is the frontends' job.
- A capability is added to the library first, then surfaced in the CLI and/or the MCP server.
- Long-running operations (watching builds, streaming logs) are exposed by the library as
  iterators/streams so each frontend can present them its own way.

## Security model

These are design constraints, not guidelines:

- The user's credentials (password, GitHub token) are never seen, stored, or logged.
- Authentication is a browser-based GitHub login flow. Only the resulting Odoo.sh session is kept
  across runs, in the OS keyring — never in a plaintext file, config file, or cache.
- The store accepts three keyring backends and picks among them itself, not through
  `keyring.get_keyring()`: Secret Service (Linux, and WSL2 once a provider is installed), macOS
  Keychain, Windows Credential Locker. Any other backend (`fail`, `null`, a chainer pick,
  `keyrings.alt`, libsecret, KWallet, any third party) is an error with a message, not a fallback.
- With no accepted backend, as on a bare WSL2, in a container or in CI, nothing is persisted. The
  error names the two ways out: install a Secret Service provider, or supply the session through
  the environment. The session is never written to a file or printed for the shell to export.
- Upstream expiry is authoritative: an unauthenticated response invalidates the stored session and
  requires a new login. Sessions are never refreshed or extended. A client-side max age applies
  on top of upstream expiry.
- Headless use takes the session from the environment and keeps it in memory only.
- Session values must not appear in logs, exceptions, `repr()`s, CLI output, or MCP tool results.
- The MCP server is read-only by default; tools that change state on Odoo.sh are opt-in and
  documented as such. Every tool documents what it does and what it can touch.

Open question (decide before implementing auth; record the outcome here):

- How the session is captured at the end of the browser flow.

## Commands

Toolchain: uv (never `pip`), ruff, basedpyright, deptry, vulture, pytest, zensical, prek.
Python >= 3.12; `.python-version` pins 3.12 locally so the floor is what gets exercised, and CI
tests 3.12 to 3.14.

```bash
make install        # uv sync + install the git hooks
make check          # full gate, non-mutating: what CI runs
make format         # ruff format
make lint           # ruff check with fixes, zizmor on the workflows
make type-check     # basedpyright
make deps           # deptry, once per package
make test           # pytest
make coverage       # pytest with coverage; fail_under = 90
make docs           # zensical build --strict, into site/
make build          # wheel + sdist of each package, into dist/
make hooks          # every prek hook over every tracked file

uv run pytest packages/odouche                               # one package
uv run pytest packages/odouche/tests/test_x.py::test_name    # one test
uv run osh --help                                            # run the CLI from the workspace
uv add --package odouche-cli <dep>                           # add a dependency to one package
uv add --dev <dep>                                           # add a development tool (root)
```

Tool configuration lives in the root `pyproject.toml`, except basedpyright (`pyrightconfig.json`)
and each package's own deptry exceptions. The hooks in `.pre-commit-config.yaml` run the Python
tools through `uv run`, so they use the versions `uv.lock` pins.

## Commits and releases

- Conventional Commits; pull requests are squash-merged, so the PR title is the commit and CI
  checks it.
- Never edit a version. Release Please owns them: the three packages and the workspace root are
  versioned in lockstep, and the `# x-release-please-version` markers in the package manifests are
  what it rewrites (including the `odouche==X` pin in the two frontends).
- Merging the release PR tags the release and publishes to PyPI by trusted publishing
  (`.github/workflows/release.yml`). CONTRIBUTING.md has the two things to check before merging one.

## Testing

Tests never contact the real Odoo.sh. Upstream responses are mocked or replayed from fixtures,
and fixtures must be scrubbed of session values and real project data before being committed.
