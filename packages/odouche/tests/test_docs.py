import copy
import getpass
import re
from pathlib import Path
from urllib.parse import urlencode

import httpx2
import pytest

import odouche
from odouche import KEYRING_ENTRY, KEYRING_SERVICE, Secret, _login
from odouche._upstream import backups as backups_layer, logs


ROOT = Path(__file__).parents[3]
GUIDE = ROOT / "docs" / "library.md"
README = ROOT / "packages" / "odouche" / "README.md"
REFERENCE = ROOT / "docs" / "reference.md"
BLOCK = re.compile(r"^```python\n(.*?)^```$", re.MULTILINE | re.DOTALL)
ENTRY = re.compile(r"^::: (\S+)$", re.MULTILINE)
BUILDS = "/app/branch/51044/builds"
BACKUPS = "/app/project/acme-corp-odoo-addons-4217/backups"
INFO = "/app/project/acme-shop/get_info"
LOG = b"Installing modules\nModules loaded\n"
# What the guide is to show, each by a call only its example makes.
SHOWN = [
    "odouche.login(",
    "odouche.logout(",
    ".projects()",
    ".branches(",
    ".backups(",
    ".builds(",
    ".history(",
    ".branch_settings(",
    ".watch_build(",
    ".read_log(",
    ".follow_log(",
    ".rebuild(",
    ".create_backup(",
    ".download(",
    "except odouche.OdoucheError",
]


def blocks(path):
    """Return the Python examples of a page, each with the line it starts at."""
    text = path.read_text(encoding="utf-8")
    return [(text.count("\n", 0, match.start(1)) + 1, match.group(1)) for match in BLOCK.finditer(text)]


EXAMPLES = [
    pytest.param(path, line, source, id=f"{path.name}:{line}")
    for path in (GUIDE, README)
    for line, source in blocks(path)
]


def log(request):
    """Answer a range of a log as a worker does."""
    asked = request.headers["Range"]
    first = max(len(LOG) - int(asked[7:]), 0) if asked.startswith("bytes=-") else int(asked[6:-1])
    headers = {"Content-Range": f"bytes {first}-{len(LOG) - 1}/{len(LOG)}"}
    return httpx2.Response(206, headers=headers, content=LOG[first:])


@pytest.fixture
def odoo_sh(upstream, backend, session, monkeypatch, tmp_path):
    """Stand in for Odoo.sh, the keyring, the browser and the time, for an example to run as written."""
    # Where an example writes its file.
    monkeypatch.chdir(tmp_path)
    listed = upstream.bodies[BUILDS]["result"][0]["builds"]
    # A finished build on a worker: a watch of it ends, and it has logs.
    listed[0].update(listed[1] | {"id": listed[0]["id"]})
    upstream.bodies[f"/paas/build/{listed[0]['id']}/logs/list"] = upstream.load("build_logs_list.json")
    for name in ("install", "odoo"):
        upstream.bodies[f"/paas/build/{listed[0]['id']}/logs/{name}"] = log

    def rebuild(_):
        listed.insert(0, copy.deepcopy(listed[0]) | {"id": listed[0]["id"] + 1})
        return httpx2.Response(200, json=upstream.load("rebuild.json"))

    upstream.bodies["/app/branch/51044/rebuild"] = rebuild
    # Rebuilt and backed up both.
    upstream.bodies[BUILDS]["result"][0]["branch_info"]["stage"] = "staging"
    backups = upstream.bodies[BACKUPS]["result"]

    def dump(_):
        new = {"name": listed[0]["name"], "backup_datetime_utc": "2026-10-14 13:05:41"}
        backups.insert(0, copy.deepcopy(backups[0]) | new)
        return httpx2.Response(200, json=upstream.load("dump.json"))

    upstream.bodies[f"/app/build/{listed[0]['id']}/dump"] = dump
    # The staging backup's build, on a worker that has prepared its file.
    staging = copy.deepcopy(upstream.bodies[BUILDS])
    staging["result"][0]["branch_info"] |= {"id": 51020, "name": "staging"}
    staging["result"][0]["builds"] = [listed[1] | {"id": 88124, "name": backups[0]["name"]}]
    upstream.bodies["/app/branch/51020/builds"] = staging
    worker, taken = listed[1]["worker_url"], backups[0]["backup_datetime_utc"]
    link = f"{worker}/paas/build/88124/download/dump?{urlencode({'backup_datetime_utc': taken, 'test_dump': 1, 'filestore': 1})}"
    ready = {"id": 9001, "notif_type": "dump", "buttons": [{"type": "download", "url": link}]}

    def prepare(_):
        upstream.bodies[INFO]["result"]["notifications"]["4217"]["items"].append(ready)
        return httpx2.Response(200, json=upstream.load("dump.json"))

    upstream.bodies["/app/build/88124/dump"] = prepare
    upstream.bodies["/paas/build/88124/token"] = lambda _: httpx2.Response(
        302, headers={"Location": link.replace("?", "?token=t0k3n&")}
    )
    upstream.bodies["/paas/build/88124/download/dump"] = lambda _: httpx2.Response(200, content=b"PK")
    now = [0.0]
    monkeypatch.setattr(logs, "_monotonic", lambda: now[0])
    monkeypatch.setattr(logs, "_sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    monkeypatch.setattr(backups_layer, "_monotonic", lambda: now[0])
    monkeypatch.setattr(backups_layer, "_sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    monkeypatch.setattr(_login, "_find", lambda: None)
    monkeypatch.setattr(_login, "_transport", upstream.connect)
    monkeypatch.setattr(getpass, "getpass", lambda _: session)
    # As after a login: the session is the stored one.
    odouche.login(ask=lambda: Secret(session))
    upstream.requests.clear()
    return upstream


@pytest.mark.parametrize(("path", "line", "source"), EXAMPLES)
def test_an_example_runs_as_written(path, line, source, odoo_sh, capsys, session):
    # Compiled at its place in the page, so a failure names the line of the example.
    exec(compile("\n" * (line - 1) + source, str(path), "exec"), {"__name__": "__main__"})  # noqa: S102

    assert odoo_sh.requests
    assert session not in capsys.readouterr().out


def test_the_logout_example_deletes_the_stored_session(odoo_sh, backend):
    [source] = [source for _, source in blocks(GUIDE) if "odouche.logout(" in source]

    exec(source, {})  # noqa: S102

    assert (KEYRING_SERVICE, KEYRING_ENTRY) not in backend.entries


def test_the_guide_shows_every_capability():
    sources = [source for _, source in blocks(GUIDE)]

    assert [call for call in SHOWN if not any(call in source for source in sources)] == []


def test_the_reference_has_an_entry_for_every_exported_name_and_no_other():
    entries = ENTRY.findall(REFERENCE.read_text(encoding="utf-8"))

    assert sorted(entries) == sorted(f"odouche.{name}" for name in odouche.__all__)
