"""``pdf-toolkit`` command line.

Errors are reported by type only unless ``--debug`` is given: a Python traceback can quote file
paths and values, which is exactly what this tool must not print.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pdf_redaction.engines.base import EngineError
from pdf_redaction.guards import GuardError
from pdf_toolkit import __version__
from pdf_toolkit.config import AppConfig, default_path
from pdf_toolkit.modules import discover


def _config(args, cfg: AppConfig) -> int:
    if args.action == "init":
        path = AppConfig.write_template(Path(args.config) if args.config else None)
        print(f"configuration template written ({path.name}); open it with: pdf-toolkit config edit")
        return 0
    if args.action == "edit":
        from pdf_toolkit.gui.files import open_with_default_app

        open_with_default_app(cfg.path)
        return 0
    r = cfg.redaction
    print(f"configuration file: {'found' if cfg.path.exists() else 'missing (run: pdf-toolkit config init)'}")
    print(f"global term files: {len(r.global_term_files)} ({sum(p.exists() for p in r.global_term_files)} exist)")
    print(f"global alias files: {len(r.global_alias_files)} ({sum(p.exists() for p in r.global_alias_files)} exist)")
    print(f"pattern packs: {', '.join(r.pattern_packs)}; engines: {', '.join(r.engines)}; workers: {r.workers}")
    print(
        f"workspace_root set: {bool(r.workspace_root)}; output_root set: {bool(r.output_root)}; "
        f"protected locations: {len(r.protected_locations)}"
    )
    key = r.engine_settings.get("stirling", {}).get("api_key_file")
    print(
        f"Stirling API key file: {'set' if key else 'not set'}{' (missing)' if key and not Path(key).exists() else ''}"
    )
    return 0


def _gui(args, cfg: AppConfig) -> int:
    from pdf_toolkit.gui.shell import run_gui

    return run_gui(cfg)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pdf-toolkit", description="Modular PDF toolkit")
    parser.add_argument("--version", action="version", version=f"pdf-toolkit {__version__}")
    parser.add_argument("--config", help=f"configuration file (default: {default_path().name} in the user folder)")
    parser.add_argument("--debug", action="store_true", help="show full tracebacks (may print paths!)")
    sub = parser.add_subparsers(dest="command", required=True)

    c = sub.add_parser("config", help="create or check the configuration")
    c.add_argument("action", choices=["init", "check", "edit"])
    c.set_defaults(handler=_config)

    g = sub.add_parser("gui", help="open the graphical interface")
    g.set_defaults(handler=_gui)

    for module in discover():
        module.add_cli(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = AppConfig.load(Path(args.config) if args.config else None)
        return args.handler(args, cfg)
    except (GuardError, EngineError, FileExistsError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        if args.debug:
            raise
        print(
            f"error: {type(exc).__name__} (run with --debug for details; output may then include paths)",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
