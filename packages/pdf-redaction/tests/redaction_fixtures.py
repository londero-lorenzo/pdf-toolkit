"""Shared test helpers and fixtures (also used by the app tests). Every value here is invented."""

from __future__ import annotations

import io
import re
import threading
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from pypdf import PdfReader

from pdf_core import inspect_pdf
from pdf_core.testing import make_pdf
from pdf_redaction.engines.base import EngineResult
from pdf_redaction.engines.text import TextEngine
from pdf_redaction.rules.context import RedactionContext, context_dir
from pdf_redaction.rules.terms import write_aliases, write_terms
from pdf_redaction.textredact import TextRedactor

PERSON = "Jane Example"
POLICY = "00999888777666555"
TAX_CODE = "XMPJNE85M41Z999K"  # shape of an Italian tax code, invented
EMAIL = "jane.example@example.org"


class ReferenceEngine:
    """Offline stand-in for Stirling: rebuilds the PDF from redacted text lines."""

    name = "reference"
    version = "1"
    suffixes = frozenset({".pdf"})

    def __init__(self, settings=None):
        self.calls = 0

    def redact(self, src: Path, dst: Path, ctx: RedactionContext) -> EngineResult:
        self.calls += 1
        redactor = TextRedactor(ctx)
        pages = [[redactor.apply(line) for line in (p.extract_text() or "").splitlines()] for p in PdfReader(src).pages]
        make_pdf(dst, pages, image_pages=inspect_pdf(src).image_pages)
        return EngineResult(counts=dict(redactor.counts), remote_calls=1)


class LeakyEngine(ReferenceEngine):
    """Simulates Stirling's silent box-only fallback: the text stays in the file."""

    name = "leaky"

    def redact(self, src, dst, ctx):
        dst.write_bytes(Path(src).read_bytes())
        return EngineResult(remote_calls=1)


@pytest.fixture
def source(tmp_path) -> Path:
    """A source folder shaped like a real archive, filled with invented data."""
    root = tmp_path / "source"
    folder = root / f"Customer_Profile_n.{POLICY}-{PERSON}"
    make_pdf(
        folder / "statement_2025-12.pdf",
        [[f"Holder: {PERSON}", f"Policy {POLICY}", f"Tax code {TAX_CODE}", "Value 12.345,67 EUR"]],
        info={"Author": PERSON},
    )
    make_pdf(root / f"ABCDE{POLICY}.pdf", [["Annual report", f"Contact {EMAIL}"]], image_pages=[1])
    (root / "movements.csv").write_text(
        f"date;holder;amount\n2025-01-31;{PERSON};100,00\n2025-02-28;{PERSON};200,00\n", encoding="utf-8"
    )
    (root / "notes.docx").write_bytes(b"PK\x03\x04 not really a docx")
    write_terms(context_dir(root) / "terms.txt", [PERSON])
    write_aliases(context_dir(root) / "aliases.csv", [(POLICY, "POL-A")])
    return root


@pytest.fixture
def ctx(source) -> RedactionContext:
    return RedactionContext.load(source, default_packs=["common", "it"])


@pytest.fixture
def engines():
    return {"reference": ReferenceEngine(), "text": TextEngine()}


class FakeStirling(BaseHTTPRequestHandler):
    requests: list[dict] = []
    api_key = "test-key"
    fail_with: int | None = None

    def log_message(self, *args):
        pass

    def _parts(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        msg = BytesParser(policy=HTTP).parsebytes(
            b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\n\r\n" + body
        )
        fields, files = {}, {}
        for part in msg.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if part.get_filename():
                files[name] = (part.get_filename(), part.get_payload(decode=True))
            else:
                fields.setdefault(name, []).append(part.get_content().strip())
        return fields, files

    def do_GET(self):
        self._reply(b'{"status":"UP","version":"3.1.0"}', "application/json")

    def do_POST(self):
        if self.headers.get("X-API-KEY") != self.api_key:
            return self._reply(b"unauthorized", status=401)
        if FakeStirling.fail_with:
            return self._reply(b"Invalid regex pattern: secret", status=FakeStirling.fail_with)
        fields, files = self._parts()
        FakeStirling.requests.append({"path": self.path, "fields": fields, "files": files})
        filename, data = files["fileInput"]
        if self.path.endswith("auto-redact"):
            rules = [re.compile(p) for p in fields["listOfText"][0].split("\n")]
            pages = []
            for page in PdfReader(io.BytesIO(data)).pages:
                lines = (page.extract_text() or "").splitlines()
                for rx in rules:
                    lines = [rx.sub("", line) for line in lines]
                pages.append(lines)
            buf = io.BytesIO()
            tag = threading.get_ident()  # requests run in parallel threads
            make_pdf_path = self.server.tmp / f"out-{tag}.pdf"
            (self.server.tmp / f"in-{tag}.pdf").write_bytes(data)
            make_pdf(make_pdf_path, pages, image_pages=inspect_pdf(self.server.tmp / f"in-{tag}.pdf").image_pages)
            buf.write(make_pdf_path.read_bytes())
            return self._reply(buf.getvalue(), "application/pdf")
        return self._reply(data, "application/pdf")  # sanitize: unchanged

    def _reply(self, body, ctype="text/plain", status=200):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def server(tmp_path):
    FakeStirling.requests = []
    FakeStirling.fail_with = None
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeStirling)
    httpd.tmp = tmp_path
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
