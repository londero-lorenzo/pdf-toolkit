"""End-to-end CLI run against a fake Stirling: nothing private may reach the console."""

import hashlib

import pytest

from pdf_redaction.rules.context import context_dir
from pdf_redaction.rules.terms import write_terms
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
    assert cli(config, "redact", "review", "sample-2025", "missing.pdf") == 1
    assert cli(config, "redact", "review", "sample-2025", "ABCDEPOL-A.pdf") == 0
    assert cli(config, "redact", "publish", "sample-2025") == 0
    out = capsys.readouterr()
    assert_clean(out.out + out.err)
    assert "remote engine calls: 4" in out.out
    assert tree_hash(source) == before
    published = tmp_path / "shared" / "out" / "sample-2025"  # default: <output_root>/<alias>
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


def test_alias_matching_a_rule_is_refused(config, source, capsys):
    for alias in ("Jane-Example-2025", f"pol{POLICY}", "jane.example@example.org"):
        assert cli(config, "redact", "new", str(source), alias) == 1
    err = capsys.readouterr().err
    assert err.count("alias matches a redaction rule") == 3
    assert_clean(err)


def test_help_of_the_main_steps(capsys):
    for cmd in ("new", "run", "review", "publish"):
        with pytest.raises(SystemExit):
            main(["redact", cmd, "--help"])
        assert "docs/redaction-guide.md" in capsys.readouterr().out


def test_publish_to_a_folder_is_remembered(tmp_path, config, source, capsys):
    x, y = tmp_path / "send" / "x", tmp_path / "send" / "y"
    assert cli(config, "redact", "new", str(source), "sample-2025") == 0
    cli(config, "redact", "run", "sample-2025")
    assert cli(config, "redact", "review", "sample-2025", "ABCDEPOL-A.pdf") == 0
    capsys.readouterr()
    assert cli(config, "redact", "publish", "sample-2025", "--to", str(x)) == 0
    out = capsys.readouterr().out
    assert "destination (--to)" in out and (x / "movements.csv").exists()
    assert not (tmp_path / "shared" / "out" / "sample-2025").exists()
    assert cli(config, "redact", "publish", "sample-2025") == 0  # no --to: the last destination again
    out = capsys.readouterr().out
    assert "destination (last used)" in out and "destination changed" not in out
    assert not (tmp_path / "shared" / "out" / "sample-2025").exists()
    assert cli(config, "redact", "publish", "sample-2025", "--to", str(y)) == 0
    out = capsys.readouterr().out
    assert "destination changed; the previous one was left as it was" in out
    assert x.as_posix() in out and "file(s) published there)" in out
    assert (x / "movements.csv").exists() and (y / "movements.csv").exists()
    assert_clean(out)


def test_publish_prints_a_hidden_marker_for_paths_matching_rules(tmp_path, config, source, capsys):
    leaky, clean = tmp_path / "send" / PERSON.replace(" ", "_"), tmp_path / "send" / "ok"
    assert cli(config, "redact", "new", str(source), "sample-2025") == 0
    cli(config, "redact", "run", "sample-2025")
    capsys.readouterr()
    cli(config, "redact", "publish", "sample-2025", "--to", str(leaky))
    cli(config, "redact", "publish", "sample-2025", "--to", str(clean))
    out = capsys.readouterr()
    assert out.out.count("(folder hidden: its path matches a redaction rule)") == 2  # as current, then as previous
    assert_clean(out.out + out.err)


def test_publish_needs_a_destination_without_output_root(tmp_path, source, server, capsys):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f'[redaction]\nworkspace_root = "{(tmp_path / "ws").as_posix()}"\nengines = ["text"]\n', encoding="utf-8"
    )
    assert cli(cfg, "redact", "new", str(source), "sample-2025") == 0
    capsys.readouterr()
    assert cli(cfg, "redact", "publish", "sample-2025") == 1
    assert "no destination" in capsys.readouterr().err


def test_publish_refuses_a_destination_inside_workspace_root(tmp_path, config, source, capsys):
    assert cli(config, "redact", "new", str(source), "sample-2025") == 0
    capsys.readouterr()
    assert (
        cli(config, "redact", "publish", "sample-2025", "--to", str(tmp_path / "private" / "workspaces" / "out")) == 1
    )
    assert "must not contain each other" in capsys.readouterr().err


def test_publish_hides_paths_that_match_new_rules(config, source, capsys):
    assert cli(config, "redact", "new", str(source), "sample-2025") == 0
    cli(config, "redact", "run", "sample-2025")
    write_terms(context_dir(source) / "terms.txt", [PERSON, "movements"])
    capsys.readouterr()
    assert cli(config, "redact", "publish", "sample-2025") == 2  # rules changed: everything held back
    out = capsys.readouterr().out
    assert "HOLD file#" in out and "movements" not in out
