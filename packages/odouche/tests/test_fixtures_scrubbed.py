import ipaddress
import re
from pathlib import Path


PACKAGES = Path(__file__).parents[2]

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
SCRUBBED_DOMAIN = "example.com"
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
# RFC 5737: the three IPv4 ranges kept for documentation.
DOCUMENTATION = tuple(ipaddress.ip_network(net) for net in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24"))


def unscrubbed_addresses(directory: Path) -> list[str]:
    findings: list[str] = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for number, line in enumerate(lines, start=1):
            for match in EMAIL.finditer(line):
                domain = match.group(1).lower()
                if domain != SCRUBBED_DOMAIN and not domain.endswith(f".{SCRUBBED_DOMAIN}"):
                    findings.append(f"{path}:{number}: {match.group(0)}")
            findings.extend(
                f"{path}:{number}: {match.group(0)}"
                for match in IPV4.finditer(line)
                if not _documentation(match.group(0))
            )
    return findings


def _documentation(text: str) -> bool:
    try:
        address = ipaddress.IPv4Address(text)
    except ValueError:
        return False
    return any(address in network for network in DOCUMENTATION)


def test_clean_fixture_passes(tmp_path):
    (tmp_path / "projects.json").write_text(
        '{"owner": "dev@example.com", "bot": "ci@mail.example.com", "cookie": "session_id=REDACTED"}\n'
    )

    assert unscrubbed_addresses(tmp_path) == []


def test_dirty_fixture_is_reported(tmp_path):
    (tmp_path / "clean.json").write_text('{"author": "dev@example.com"}\n')
    dirty = tmp_path / "builds" / "dirty.json"
    dirty.parent.mkdir()
    dirty.write_text('{\n  "author": "jane@acme.test",\n  "reviewer": "bob@notexample.com"\n}\n')

    assert unscrubbed_addresses(tmp_path) == [
        f"{dirty}:2: jane@acme.test",
        f"{dirty}:3: bob@notexample.com",
    ]


def test_an_ip_address_outside_the_documentation_ranges_is_reported(tmp_path):
    (tmp_path / "allow_ip.json").write_text(
        '{"result": "203.0.113.7", "real": "81.2.69.160", "version": "18.0.1.3.0"}\n'
    )

    assert unscrubbed_addresses(tmp_path) == [f"{tmp_path / 'allow_ip.json'}:1: 81.2.69.160"]


def test_committed_fixtures_are_scrubbed():
    findings = [
        finding
        for directory in sorted(PACKAGES.glob("*/tests/fixtures"))
        for finding in unscrubbed_addresses(directory)
    ]

    assert not findings, "fixtures hold addresses outside example.com or the IPv4 documentation ranges:\n" + "\n".join(
        findings
    )
