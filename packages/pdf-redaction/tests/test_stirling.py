"""StirlingEngine against a fake Stirling server on 127.0.0.1 (no real Stirling needed)."""

from pathlib import PurePosixPath

import pytest

from pdf_redaction.engines.base import EngineError, load_engines
from pdf_redaction.engines.stirling import StirlingClient, StirlingEngine, ensure_loopback
from pdf_redaction.verify import Status, verify_file
from redaction_fixtures import PERSON, FakeStirling, server  # noqa: F401


@pytest.fixture
def key_file(tmp_path):
    f = tmp_path / "key.txt"
    f.write_text("test-key\n", encoding="utf-8")
    return f


@pytest.mark.parametrize(
    "url", ["http://example.com", "http://10.0.0.5:8080", "ftp://127.0.0.1", "http://127.0.0.1.evil.com"]
)
def test_only_loopback(url):
    with pytest.raises(EngineError):
        ensure_loopback(url)


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1:8080", "http://localhost:8080/", "http://[::1]:8080", "https://127.0.0.2"]
)
def test_loopback_accepted(url):
    assert ensure_loopback(url)


def test_redact_sends_neutral_name_and_key(tmp_path, server, key_file, source, ctx, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://10.255.255.1:9")  # must be ignored
    engine = StirlingEngine({"url": server, "api_key_file": str(key_file)})
    src = next(source.rglob("statement_2025-12.pdf"))
    out = tmp_path / "out" / "x.pdf"
    result = engine.redact(src, out, ctx)
    assert result.remote_calls == 2
    assert [r["path"] for r in FakeStirling.requests] == [
        "/api/v1/security/auto-redact",
        "/api/v1/security/sanitize-pdf",
    ]
    assert all(r["files"]["fileInput"][0] == "document.pdf" for r in FakeStirling.requests)
    assert FakeStirling.requests[0]["fields"]["useRegex"] == ["true"]
    assert verify_file(out, PurePosixPath("x.pdf"), ctx).status is Status.OK


def test_errors_never_echo_the_body(tmp_path, server, key_file, source, ctx):
    FakeStirling.fail_with = 400
    engine = StirlingEngine({"url": server, "api_key_file": str(key_file)})
    with pytest.raises(EngineError) as info:
        engine.redact(next(source.rglob("*.pdf")), tmp_path / "o.pdf", ctx)
    assert "secret" not in str(info.value) and "400" in str(info.value)


def test_wrong_key(tmp_path, server, source, ctx):
    bad = tmp_path / "bad.txt"
    bad.write_text("nope", encoding="utf-8")
    with pytest.raises(EngineError, match="401"):
        StirlingEngine({"url": server, "api_key_file": str(bad)}).redact(
            next(source.rglob("*.pdf")), tmp_path / "o.pdf", ctx
        )


def test_status_and_unreachable(server):
    assert StirlingClient(server).status()["version"] == "3.1.0"
    with pytest.raises(EngineError, match="not reachable"):
        StirlingClient("http://127.0.0.1:9", timeout=2).status()


def test_engines_discovered_by_entry_point():
    engines = load_engines({"stirling": {"url": "http://127.0.0.1:8080"}}, ["stirling", "text"])
    assert list(engines) == ["stirling", "text"] and engines["stirling"].suffixes == {".pdf"}
    assert PERSON  # fixtures module importable
