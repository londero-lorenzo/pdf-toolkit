"""End-to-end CLI run against a fake Stirling: nothing private may reach the console."""

import hashlib

from pdf_toolkit.cli import main
from redaction_fixtures import EMAIL, PERSON, POLICY, TAX_CODE

SECRETS = [PERSON, *PERSON.split(), POLICY, TAX_CODE, EMAIL, "Customer_Profile_n.0099", "ABCDE0099"]


def tree_hash(root):
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(root).as_posix().encode() + p.read_bytes())
    return h.hexdigest()


def cli(config, *args):
    return main(["--config", str(config), *args])


def assert_clean(text):
    for secret in SECRETS:
        assert secret not in text, "a private value reached the console"


def test_full_cycle_prints_nothing_private(tmp_path, config, source, capsys):
    before = tree_hash(source)
    assert cli(config, "config", "check") == 0
    assert cli(config, "redact", "context", str(source)) == 0
    assert cli(config, "redact", "new", str(source), "sample-2025") == 0
    assert cli(config, "redact", "preview-names", "sample-2025") == 0
    assert cli(config, "redact", "run", "sample-2025") == 2  # one WARN (image), no FAIL
    assert cli(config, "redact", "verify", "sample-2025") == 2
    assert cli(config, "redact", "publish", "sample-2025") == 2  # WARN file held back
    assert cli(config, "redact", "review", "sample-2025", "ABCDEPOL-A.pdf") == 0
    assert cli(config, "redact", "publish", "sample-2025") == 0
    out = capsys.readouterr()
    assert_clean(out.out + out.err)
    assert "remote engine calls: 4" in out.out
    assert tree_hash(source) == before
    published = tmp_path / "shared" / "out" / "sample-2025"
    assert (published / "ABCDEPOL-A.pdf").exists()
    for p in published.rglob("*"):
        if p.is_file():
            assert_clean(p.relative_to(published).as_posix())


def test_workspace_in_protected_location_is_refused(tmp_path, config, source, capsys):
    code = cli(config, "redact", "new", str(source), "x", "--workspace", str(tmp_path / "shared" / "ws"))
    assert code == 1 and "protected location" in capsys.readouterr().err


def test_unexpected_errors_hide_details(tmp_path, config, capsys):
    missing = tmp_path / PERSON
    assert cli(config, "redact", "context", str(missing)) == 0  # empty context, no crash
    code = cli(config, "redact", "run", str(missing))
    err = capsys.readouterr().err
    assert code == 1 and PERSON not in err


def test_audit_repo_command(tmp_path, config, source, capsys):
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "README.md").write_text(f"made by {PERSON}\n", encoding="utf-8")
    assert cli(config, "redact", "audit-repo", str(repo), "--source", str(source)) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert_clean(out)
