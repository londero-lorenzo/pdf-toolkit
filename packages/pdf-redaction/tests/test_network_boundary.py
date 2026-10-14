"""Only engines/stirling.py may contain networking code, in the whole repository."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ALLOWED = {Path("packages/pdf-redaction/src/pdf_redaction/engines/stirling.py")}
NETWORK = re.compile(
    r"^\s*(?:import|from)\s+(urllib|http|socket|ssl|requests|httpx|aiohttp|ftplib|smtplib|websocket|xmlrpc)\b", re.M
)


def test_no_network_code_outside_the_stirling_engine():
    offenders = []
    for py in sorted(REPO.glob("*/*/src/**/*.py")):
        rel = py.relative_to(REPO)
        if rel not in ALLOWED and NETWORK.search(py.read_text(encoding="utf-8")):
            offenders.append(rel.as_posix())
    assert offenders == []


def test_allowed_module_exists():
    assert all((REPO / p).exists() for p in ALLOWED)
