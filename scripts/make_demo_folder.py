"""Create a demo source folder with invented documents, to try pdf-toolkit end to end.

Usage: uv run python scripts/make_demo_folder.py <empty folder>
"""

from __future__ import annotations

import sys
from pathlib import Path

from pdf_core.testing import make_pdf
from pdf_redaction.rules.context import context_dir
from pdf_redaction.rules.terms import write_aliases, write_terms

PERSON = "Jane Example"
CONTRACT = "00999888777666555"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    root = Path(sys.argv[1])
    if root.exists() and any(root.iterdir()):
        print("the folder must be empty or missing")
        return 1
    folder = root / f"Customer_Profile_n.{CONTRACT}-{PERSON}"
    make_pdf(
        folder / "statement_2025-12.pdf",
        [
            ["Annual statement 2025", f"Holder: {PERSON}", f"Contract {CONTRACT}", "Tax code XMPJNE85M41Z999K"],
            ["Return 2025: 3.10%", "Surrender value 12.345,67 EUR", "Contact: jane.example@example.org"],
        ],
        info={"Author": PERSON, "Title": "Statement"},
    )
    make_pdf(root / f"ABCDE{CONTRACT}.pdf", [["Policy conditions", "Guaranteed rate 0.50%"]], image_pages=[1])
    (root / "movements.csv").write_text(
        f"date;holder;amount\n2025-01-31;{PERSON};100,00\n2025-02-28;{PERSON};200,00\n", encoding="utf-8"
    )
    write_terms(context_dir(root) / "terms.txt", [PERSON])
    write_aliases(context_dir(root) / "aliases.csv", [(CONTRACT, "POL-A")])
    print("demo folder created (all data invented). Next:")
    print(f'  uv run pdf-toolkit redact new "{root}" demo-2025')
    print("  uv run pdf-toolkit redact run demo-2025")
    return 0


if __name__ == "__main__":
    sys.exit(main())
