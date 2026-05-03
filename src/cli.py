"""CLI entry point for pdf2md."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .parser import PDFParser
from .renderer import MarkdownRenderer


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pdf2md",
        description="Convert 42 campus LaTeX-generated PDFs to Markdown",
    )
    parser.add_argument("input", help="Input PDF file path")
    parser.add_argument("-o", "--output", help="Output Markdown file path (default: stdout)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print info to stderr")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    if args.verbose:
        print(f"Parsing {input_path}...", file=sys.stderr)

    pdf_parser = PDFParser(input_path)
    document = pdf_parser.parse()

    if args.verbose:
        print(f"Extracted {len(document.elements)} elements", file=sys.stderr)

    renderer = MarkdownRenderer()
    markdown = renderer.render(document)

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(markdown, encoding="utf-8")
        if args.verbose:
            print(f"Written to {output_path}", file=sys.stderr)
    else:
        sys.stdout.write(markdown)


if __name__ == "__main__":
    main()
