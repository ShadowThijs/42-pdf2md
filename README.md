# pdf2md

Converts 42 campus LaTeX-generated PDFs to clean Markdown. Standard tools like `pdftotext` lose all formatting on these PDFs. This converter uses PyMuPDF to extract font sizes, colors, drawing elements, and text positions to reconstruct the document structure as Markdown.

## What it handles

- Title pages and subtitles
- Table of contents with numbered entries
- Chapter and section headings (from font size hierarchy)
- Bold, italic, and inline code formatting
- Bullet and sub-bullet lists
- Blockquotes with attribution
- Fenced code blocks (detected from gray-bordered regions)
- Exercise description tables (from line-grid drawings)
- Callout boxes (from colored rectangles) as blockquotes
- Good/bad practice sections
- Hyphenation joining across line breaks

## Install

You need Python 3.10+.

**With uv** (recommended):

```sh
uv venv
source .venv/bin/activate
uv pip install -e .
```

**With pip and venv**:

```sh
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Either way, this installs the `pdf2md` command.

## Usage

Convert a PDF to a file:

```sh
pdf2md subject.pdf -o subject.md
```

Or pipe to stdout:

```sh
pdf2md subject.pdf
```

With verbose output (prints progress to stderr):

```sh
pdf2md subject.pdf -o subject.md -v
```

You can also run it as a Python module:

```sh
python -m src.cli subject.pdf -o subject.md
```

## Making changes

The code is organized as a three-stage pipeline:

```
PDF  -->  Parser  -->  Document Model  -->  Renderer  -->  Markdown
```

| File | What it does |
|---|---|
| `src/parser.py` | Extracts text, fonts, positions, and drawings from PDF pages using PyMuPDF. Detects headings from font sizes, code blocks from gray rectangles, callout boxes from colored fills, exercise tables from line grids. |
| `src/models.py` | Data classes: `DocElement`, `TextSpan`, `Document`, `ElementType` enum. The intermediate representation between parser and renderer. |
| `src/renderer.py` | Converts the document model to a Markdown string. Handles spacing between block elements, list formatting, and text span rendering. |
| `src/config.py` | Constants: font size thresholds, color codes, x/y position thresholds. Tweak these if a different 42 PDF has slightly different sizing. |
| `src/cli.py` | CLI entry point with argparse. Wires parser and renderer together. |

### Key detection logic

The parser identifies elements by combining signals:

- **Headings**: Font size clustering. Large (~25pt) bold text is a chapter heading, medium (~17pt) bold is a section.
- **Code blocks**: Small (~8pt) monospace text with light gray color, bounded by gray horizontal lines in the drawings.
- **Callout boxes**: Text inside colored rectangles (non-white, non-black fills in page drawings).
- **Exercise tables**: Text inside black line-grid regions (horizontal lines in drawings).
- **Formatting**: Bold/italic from PyMuPDF font flags, code from font name containing "LMMono".

If a particular PDF isn't converting well, the constants in `config.py` are the first thing to check. You can also add print statements in `parser.py` to dump the raw spans and drawings for a page to see what signals are available.

## Lint

```sh
make lint
```

Runs flake8 and mypy.

## Build

```sh
make build
```

Creates a distributable package in `dist/`.

## Dependencies

- **PyMuPDF** (`fitz`) -- PDF text and drawing extraction
- Python standard library only for everything else
