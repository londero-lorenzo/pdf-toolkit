import json

import pytest

from redaction_fixtures import ctx, engines, server, source  # noqa: F401


@pytest.fixture
def config(tmp_path, server):
    key = tmp_path / "key.txt"
    key.write_text("test-key", encoding="utf-8")
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f"""
[redaction]
pattern_packs = ["common", "it"]
workspace_root = {json.dumps(str(tmp_path / "private" / "workspaces"))}
output_root = {json.dumps(str(tmp_path / "shared" / "out"))}
protected_locations = [{json.dumps(str(tmp_path / "shared"))}]
engines = ["stirling", "text"]
workers = 2

[engines.stirling]
url = "{server}"
api_key_file = {json.dumps(str(key))}
""",
        encoding="utf-8",
    )
    return cfg
