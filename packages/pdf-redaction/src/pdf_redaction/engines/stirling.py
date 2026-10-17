"""PDF engine backed by a self-hosted Stirling-PDF instance.

THIS IS THE ONLY MODULE OF THE PROJECT THAT OPENS NETWORK CONNECTIONS, and only to a loopback
address (127.0.0.0/8, ::1, localhost). Environment proxies are ignored on purpose.

Hardening, from a reading of Stirling-PDF v3.1.0 (see docs/stirling-notes.md):
- the uploaded file is always called ``document.pdf``: Stirling logs the original file name at INFO;
- response bodies are never surfaced: an error body may echo a redaction pattern;
- the result must always go through ``pdf_redaction.verify``: when its native engine fails,
  Stirling silently falls back to box-only redaction, which can leave the text in place.

Settings (``[engines.stirling]`` in the app configuration):
    url             = "http://127.0.0.1:8080"
    api_key_file    = "C:/path/to/stirling_api_key.txt"   (the key is read, never printed)
    endpoint        = "auto-redact" | "redact-execute"
    sanitize        = true
    timeout_seconds = 300
"""

from __future__ import annotations

import ipaddress
import json
import secrets
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from pdf_redaction.engines.base import EngineError, EngineResult
from pdf_redaction.manual import rule_digests
from pdf_redaction.rules.context import RedactionContext
from pdf_redaction.rules.java_regex import to_java_patterns

UPLOAD_NAME = "document.pdf"
DEFAULT_URL = "http://127.0.0.1:8080"


def ensure_loopback(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise EngineError("Stirling URL must be http(s)://<loopback host>:<port>")
    host = parts.hostname
    if host != "localhost":
        try:
            if not ipaddress.ip_address(host).is_loopback:
                raise ValueError
        except ValueError:
            raise EngineError("Stirling URL must point to this computer (127.0.0.1, ::1 or localhost)") from None
    return url.rstrip("/")


def _multipart(fields: list[tuple[str, str]], file_field: str, data: bytes) -> tuple[bytes, str]:
    boundary = "----pdftoolkit" + secrets.token_hex(12)
    out = bytearray()
    for name, value in fields:
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        out += value.encode("utf-8") + b"\r\n"
    out += (
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{UPLOAD_NAME}"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode()
    out += data + f"\r\n--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


class StirlingClient:
    def __init__(self, url: str = DEFAULT_URL, api_key: str | None = None, timeout: float = 300):
        self.url = ensure_loopback(url)
        self._api_key = api_key
        self.timeout = timeout
        # no ProxyHandler entries: HTTP(S)_PROXY variables must never divert documents elsewhere
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _request(self, path: str, body: bytes | None = None, content_type: str | None = None) -> bytes:
        req = urllib.request.Request(self.url + path, data=body, method="POST" if body is not None else "GET")
        if content_type:
            req.add_header("Content-Type", content_type)
        if self._api_key:
            req.add_header("X-API-KEY", self._api_key)
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            hint = {401: " (missing or wrong API key)", 403: " (API key not allowed)", 413: " (file too large)"}
            raise EngineError(f"Stirling answered HTTP {exc.code} on {path}{hint.get(exc.code, '')}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise EngineError(f"Stirling not reachable at {self.url} ({type(exc).__name__})") from None

    def status(self) -> dict:
        try:
            return json.loads(self._request("/api/v1/info/status"))
        except ValueError:
            raise EngineError("unexpected answer from /api/v1/info/status") from None

    def auto_redact(self, pdf: bytes, patterns: list[str], *, color: str = "#000000", padding: float = 0) -> bytes:
        fields = [
            ("listOfText", "\n".join(patterns)),
            ("useRegex", "true"),
            ("wholeWordSearch", "false"),
            ("redactColor", color),
            ("customPadding", str(padding)),
            ("convertPDFToImage", "false"),
        ]
        body, ctype = _multipart(fields, "fileInput", pdf)
        return self._request("/api/v1/security/auto-redact", body, ctype)

    def redact_execute(self, pdf: bytes, patterns: list[str]) -> bytes:
        fields = [("regexPatterns", p) for p in patterns]
        fields.append(("style", json.dumps({"color": "#000000", "padding": 0, "convertToImage": False})))
        body, ctype = _multipart(fields, "fileInput", pdf)
        return self._request("/api/v1/security/redact-execute", body, ctype)

    def sanitize(self, pdf: bytes) -> bytes:
        fields = [
            ("removeJavaScript", "true"),
            ("removeEmbeddedFiles", "true"),
            ("removeXMPMetadata", "true"),
            ("removeMetadata", "true"),
            ("removeLinks", "true"),
            ("removeFonts", "false"),
        ]
        body, ctype = _multipart(fields, "fileInput", pdf)
        return self._request("/api/v1/security/sanitize-pdf", body, ctype)


def _read_key(path: str | None) -> str | None:
    if not path:
        return None
    try:
        key = Path(path).read_text(encoding="utf-8-sig").strip()
    except OSError:
        raise EngineError("Stirling API key file not readable (check engines.stirling.api_key_file)") from None
    return key or None


class StirlingEngine:
    name = "stirling"
    # bump whenever the requests change, so that already redacted files are redone
    # 2: patterns rewritten to the dialect Stirling accepts (see rules/java_regex.py)
    VERSION = "2"
    version = VERSION
    suffixes = frozenset({".pdf"})

    def __init__(self, settings: dict | None = None):
        settings = settings or {}
        self.endpoint = settings.get("endpoint", "auto-redact")
        if self.endpoint not in ("auto-redact", "redact-execute"):
            raise EngineError("engines.stirling.endpoint must be 'auto-redact' or 'redact-execute'")
        self.do_sanitize = bool(settings.get("sanitize", True))
        self._settings = settings
        self._client: StirlingClient | None = None
        self.version = f"{self.VERSION}/{self.endpoint}{'+sanitize' if self.do_sanitize else ''}"

    @property
    def client(self) -> StirlingClient:
        if self._client is None:
            self._client = StirlingClient(
                self._settings.get("url", DEFAULT_URL),
                _read_key(self._settings.get("api_key_file")),
                float(self._settings.get("timeout_seconds", 300)),
            )
        return self._client

    def rule_digests(self, ctx: RedactionContext) -> frozenset[str]:
        """The patterns actually sent: an alias only adds its real value, never its replacement."""
        return rule_digests(to_java_patterns(ctx))

    def redact(self, src: Path, dst: Path, ctx: RedactionContext) -> EngineResult:
        patterns = to_java_patterns(ctx)
        data = Path(src).read_bytes()
        calls = 0
        if patterns:
            if self.endpoint == "auto-redact":
                data = self.client.auto_redact(data, patterns)
            else:
                data = self.client.redact_execute(data, patterns)
            calls += 1
        if self.do_sanitize:
            data = self.client.sanitize(data)
            calls += 1
        if not data.startswith(b"%PDF"):
            raise EngineError("Stirling did not return a PDF")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        return EngineResult(remote_calls=calls)
