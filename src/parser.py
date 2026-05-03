"""PDF extraction engine using PyMuPDF."""

from __future__ import annotations

import re
from pathlib import Path

import fitz

from .config import (
    COLOR_GREEN,
    COLOR_LIGHT_GRAY,
    COLOR_PURPLE,
    COLOR_RED,
    FONT_DINGBATS,
    FONT_MATH_SYMBOLS,
    FONT_MONO,
    LINE_Y_TOLERANCE,
    SIZE_BODY,
    SIZE_CHAPTER,
    SIZE_SUBSECTION,
    X_BODY,
    X_BULLET,
    Y_FOOTER_MIN,
    Y_HEADER_MAX,
)
from .models import DocElement, Document, ElementType, TextSpan

# Minimum x-gap between spans to insert a space
SPACE_GAP_THRESHOLD = 2.5


def _is_bold(flags: int) -> bool:
    return bool(flags & 16)


def _is_italic(flags: int) -> bool:
    return bool(flags & 2)


def _is_mono(font: str) -> bool:
    return FONT_MONO in font


def _color_matches(actual: int, target: int, tolerance: int = 0x10) -> bool:
    r1, g1, b1 = (actual >> 16) & 0xFF, (actual >> 8) & 0xFF, actual & 0xFF
    r2, g2, b2 = (target >> 16) & 0xFF, (target >> 8) & 0xFF, target & 0xFF
    return abs(r1 - r2) <= tolerance and abs(g1 - g2) <= tolerance and abs(b1 - b2) <= tolerance


def _is_header_footer(span: dict) -> bool:
    y = span["bbox"][1]
    return y < Y_HEADER_MAX or y > Y_FOOTER_MIN


def _spans_to_line_text(spans: list[dict]) -> str:
    """Join spans into a line of text, inserting spaces at x-gaps."""
    if not spans:
        return ""
    # Sort by x-position
    sorted_spans = sorted(spans, key=lambda s: (s["bbox"][0], s["bbox"][1]))
    parts: list[str] = [sorted_spans[0]["text"]]
    prev_end = sorted_spans[0]["bbox"][2]

    for span in sorted_spans[1:]:
        gap = span["bbox"][0] - prev_end
        if gap > SPACE_GAP_THRESHOLD:
            parts.append(" ")
        parts.append(span["text"])
        prev_end = span["bbox"][2]

    return "".join(parts)


def _is_symbol_span(span: dict) -> bool:
    """Check if a span is a bullet/symbol character (not content)."""
    font = span.get("font", "")
    return FONT_MATH_SYMBOLS in font or FONT_DINGBATS in font


def _build_text_spans(spans: list[dict], skip_symbols: bool = True) -> list[TextSpan]:
    """Convert raw spans to TextSpan list with proper spacing and formatting."""
    if not spans:
        return []

    content_spans = [s for s in spans if not _is_header_footer(s)]
    if skip_symbols:
        content_spans = [s for s in content_spans if not _is_symbol_span(s)]

    if not content_spans:
        return []

    content_spans.sort(key=lambda s: (s["bbox"][0], s["bbox"][1]))

    result: list[TextSpan] = []
    current_parts: list[str] = []
    current_bold = _is_bold(content_spans[0]["flags"])
    current_italic = _is_italic(content_spans[0]["flags"])
    current_code = _is_mono(content_spans[0].get("font", ""))
    prev_end = content_spans[0]["bbox"][2]

    def flush() -> None:
        if current_parts:
            text = "".join(current_parts)
            stripped = text.strip()
            if stripped:
                lead_ws = text[:len(text) - len(text.lstrip())]
                trail_ws = text[len(text.rstrip()):]
                if lead_ws:
                    result.append(TextSpan(text=lead_ws))
                result.append(TextSpan(
                    text=stripped,
                    is_bold=current_bold,
                    is_italic=current_italic,
                    is_code=current_code,
                ))
                if trail_ws:
                    result.append(TextSpan(text=trail_ws))
            else:
                result.append(TextSpan(text=text))
        current_parts.clear()

    for span in content_spans:
        bold = _is_bold(span["flags"])
        italic = _is_italic(span["flags"])
        code = _is_mono(span.get("font", ""))

        # Insert space at x-gaps
        gap = span["bbox"][0] - prev_end
        if gap > SPACE_GAP_THRESHOLD and current_parts:
            current_parts.append(" ")

        if bold != current_bold or italic != current_italic or code != current_code:
            flush()
            current_bold = bold
            current_italic = italic
            current_code = code

        current_parts.append(span["text"])
        prev_end = span["bbox"][2]

    flush()
    return result


def _fix_trailing_hyphen(spans: list[TextSpan]) -> bool:
    """Remove trailing hyphen from the last content span."""
    for i in range(len(spans) - 1, -1, -1):
        s = spans[i]
        if s.text.rstrip().endswith("-"):
            t = s.text
            stripped = t.rstrip()
            hidx = stripped.rfind("-")
            spans[i] = TextSpan(
                text=stripped[:hidx] + stripped[hidx + 1:] + t[len(stripped):],
                is_bold=s.is_bold,
                is_italic=s.is_italic,
                is_code=s.is_code,
            )
            return True
        if s.text.strip():
            return False
    return False


def _spans_plain_text(text_spans: list[TextSpan]) -> str:
    """Convert TextSpan list to plain text."""
    return "".join(s.text for s in text_spans)


class PDFParser:
    def __init__(self, pdf_path: str | Path) -> None:
        self.pdf_path = Path(pdf_path)

    def parse(self) -> Document:
        doc = fitz.open(str(self.pdf_path))
        elements: list[DocElement] = []

        if len(doc) == 0:
            return Document(elements=elements)

        elements.extend(self._parse_title_page(doc[0], 0))

        if len(doc) > 1:
            toc_elems = self._parse_toc_page(doc[1], 1)
            if toc_elems:
                elements.extend(toc_elems)
                start = 2
            else:
                start = 1

            for pn in range(start, len(doc)):
                elements.extend(self._parse_content_page(doc[pn], pn))

        return Document(elements=elements)

    def _extract_lines(self, page: fitz.Page) -> list[list[dict]]:
        """Extract spans grouped into lines by y-coordinate."""
        data = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        all_spans: list[dict] = []

        for block in data["blocks"]:
            if block["type"] != 0:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    if span["text"].strip():
                        all_spans.append(span)

        if not all_spans:
            return []

        all_spans.sort(key=lambda s: (s["bbox"][1], s["bbox"][0]))
        lines: list[list[dict]] = []
        cur: list[dict] = [all_spans[0]]
        cur_y = all_spans[0]["bbox"][1]

        for span in all_spans[1:]:
            if abs(span["bbox"][1] - cur_y) <= LINE_Y_TOLERANCE:
                cur.append(span)
            else:
                # Sort within line by x
                cur.sort(key=lambda s: s["bbox"][0])
                lines.append(cur)
                cur = [span]
                cur_y = span["bbox"][1]

        if cur:
            cur.sort(key=lambda s: s["bbox"][0])
            lines.append(cur)

        return lines

    def _line_text(self, line: list[dict]) -> str:
        return _spans_to_line_text(line).strip()

    def _line_x(self, line: list[dict]) -> float:
        return line[0]["bbox"][0]

    def _line_size(self, line: list[dict]) -> float:
        return line[0]["size"]

    def _line_font(self, line: list[dict]) -> str:
        return line[0]["font"]

    def _line_flags(self, line: list[dict]) -> int:
        return line[0]["flags"]

    # ── Title Page ──────────────────────────────────────────────────

    def _parse_title_page(self, page: fitz.Page, pn: int) -> list[DocElement]:
        lines = self._extract_lines(page)
        elements: list[DocElement] = []

        for line in lines:
            size = self._line_size(line)
            font = self._line_font(line)
            text = self._line_text(line)

            if not text:
                continue

            if size >= SIZE_CHAPTER and "Roman17" in font:
                elements.append(DocElement(
                    element_type=ElementType.TITLE, text=text, page_number=pn))
            elif size >= 19.0 and "Roman17" in font:
                elements.append(DocElement(
                    element_type=ElementType.SUBTITLE, text=text, page_number=pn))
            elif _is_italic(line[0]["flags"]) and "Summary:" in text:
                elements.append(DocElement(
                    element_type=ElementType.SUMMARY, text=text, page_number=pn))

        if elements:
            elements.append(DocElement(element_type=ElementType.HORIZONTAL_RULE, page_number=pn))
        return elements

    # ── Table of Contents ───────────────────────────────────────────

    def _parse_toc_page(self, page: fitz.Page, pn: int) -> list[DocElement] | None:
        lines = self._extract_lines(page)
        if not lines:
            return None

        first = self._line_text(lines[0])
        if first != "Contents":
            return None

        elements = [DocElement(
            element_type=ElementType.TABLE_OF_CONTENTS, text="Contents", page_number=pn)]

        toc_idx = 0
        sub_idx = 0
        for line in lines[1:]:
            text = self._line_text(line)
            x = self._line_x(line)

            if not text:
                continue
            # Skip page numbers at far right
            if re.match(r"^\d+$", text) and x > 500:
                continue
            # Skip dot-only lines
            if re.match(r"^[\.\s]+$", text):
                continue

            # Clean: remove dot leaders (sequences of dot+space) and page numbers
            clean = re.sub(r"(\s+\.){2,}", "", text).strip()
            clean = re.sub(r"\s+\d+$", "", clean).strip()
            if not clean or re.match(r"^\d+$", clean):
                continue

            is_sub = x > X_BODY + 15
            if is_sub:
                sub_idx += 1
                elements.append(DocElement(
                    element_type=ElementType.TOC_ENTRY, text=clean,
                    level=1, page_number=pn))
            else:
                toc_idx += 1
                sub_idx = 0
                elements.append(DocElement(
                    element_type=ElementType.TOC_ENTRY, text=clean,
                    level=0, page_number=pn))

        elements.append(DocElement(element_type=ElementType.HORIZONTAL_RULE, page_number=pn))
        return elements

    # ── Content Pages ───────────────────────────────────────────────

    def _parse_content_page(self, page: fitz.Page, pn: int) -> list[DocElement]:
        lines = self._extract_lines(page)
        elements: list[DocElement] = []

        # Filter headers/footers
        content_lines = [l for l in lines if not all(_is_header_footer(s) for s in l)]

        # Detect LaTeX callout boxes (colored rectangles with text inside)
        callout_boxes = self._detect_callout_boxes(page)
        # Detect grid tables (line-based tables from drawings)
        grid_regions = self._detect_grid_regions(page)

        i = 0
        while i < len(content_lines):
            line = content_lines[i]
            text = self._line_text(line)
            x = self._line_x(line)
            size = self._line_size(line)
            font = self._line_font(line)
            flags = self._line_flags(line)

            if not text:
                i += 1
                continue

            # Callout box (text inside a colored drawn rectangle)
            if callout_boxes and self._line_in_callout(line, callout_boxes):
                elems, consumed = self._parse_callout_box(
                    content_lines, i, callout_boxes, pn)
                elements.extend(elems)
                i += consumed
                continue

            # Chapter heading (~24.8pt bold)
            if size >= SIZE_CHAPTER and _is_bold(flags):
                elems, consumed = self._parse_chapter(content_lines, i, pn)
                elements.extend(elems)
                i += consumed
                continue

            # Section heading: Dingbats ● purple (~17.2pt)
            if (FONT_DINGBATS in font and size >= SIZE_SUBSECTION
                    and _color_matches(line[0]["color"], COLOR_PURPLE)):
                heading = self._heading_after_bullet(line)
                if not heading and i + 1 < len(content_lines):
                    nxt = content_lines[i + 1]
                    if self._line_size(nxt) >= SIZE_SUBSECTION and _is_bold(self._line_flags(nxt)):
                        heading = self._line_text(nxt)
                        i += 1
                elements.append(DocElement(
                    element_type=ElementType.SECTION_HEADING,
                    text=heading, page_number=pn))
                i += 1
                continue

            # Subsection heading (~17.2pt bold, e.g. "IV.1 Summary")
            if (size >= SIZE_SUBSECTION and size < SIZE_CHAPTER
                    and _is_bold(flags)):
                elements.append(DocElement(
                    element_type=ElementType.SUBSECTION_HEADING,
                    text=text, page_number=pn))
                i += 1
                continue

            # Good practice (✓ green)
            if (FONT_DINGBATS in font and "✓" in text
                    and _color_matches(line[0]["color"], COLOR_GREEN)):
                elems, consumed = self._parse_practice(
                    content_lines, i, ElementType.GOOD_PRACTICE, pn)
                elements.extend(elems)
                i += consumed
                continue

            # Bad practice (✗ red)
            if (FONT_DINGBATS in font and "✗" in text
                    and _color_matches(line[0]["color"], COLOR_RED)):
                elems, consumed = self._parse_practice(
                    content_lines, i, ElementType.BAD_PRACTICE, pn)
                elements.extend(elems)
                i += consumed
                continue

            # Code block (light mono text at ~8pt)
            if (size < SIZE_BODY and _is_mono(font)
                    and _color_matches(line[0]["color"], COLOR_LIGHT_GRAY, 0x30)):
                code_lines, consumed = self._collect_code_block(content_lines, i)
                elements.append(DocElement(
                    element_type=ElementType.CODE_BLOCK,
                    text="\n".join(code_lines), language="sh", page_number=pn))
                i += consumed
                continue

            # Bullet items (• ☛ ◦ from MathSymbols)
            if _is_symbol_span(line[0]) and text[0] in ("•", "☛", "◦"):
                is_sub = x > X_BULLET + 10 or text[0] == "◦"
                content = line[1:] if len(line) > 1 else []
                spans = _build_text_spans(content, skip_symbols=True)
                consumed = 1
                while i + consumed < len(content_lines):
                    nxt = content_lines[i + consumed]
                    nxt_text = self._line_text(nxt)
                    nxt_x = self._line_x(nxt)
                    nxt_size = self._line_size(nxt)
                    nxt_font = self._line_font(nxt)
                    if (nxt_size >= SIZE_SUBSECTION
                            or (FONT_DINGBATS in nxt_font and any(
                                c in nxt_text for c in ("✓", "✗", "●", "☛")))
                            or (_is_symbol_span(nxt[0]) and nxt_text and nxt_text[0] in ("•", "☛", "◦"))
                            or (callout_boxes and self._line_in_callout(nxt, callout_boxes))
                            or self._is_code_block_line(nxt)):
                        break
                    if nxt_x >= x - 2 and nxt_size < SIZE_SUBSECTION:
                        more_spans = _build_text_spans(nxt, skip_symbols=True)
                        more_text = _spans_plain_text(more_spans).strip()
                        if more_text:
                            if _spans_plain_text(spans).rstrip().endswith("-"):
                                _fix_trailing_hyphen(spans)
                            else:
                                spans.append(TextSpan(" "))
                            spans.extend(more_spans)
                        consumed += 1
                    else:
                        break

                plain = _spans_plain_text(spans).strip()
                etype = ElementType.SUB_BULLET_ITEM if is_sub else ElementType.BULLET_ITEM
                elements.append(DocElement(
                    element_type=etype, text=plain,
                    content=spans, page_number=pn))
                i += consumed
                continue

            # Blockquote (italic text starting with " or \u201c)
            if (_is_italic(flags) and text[0] in ('"', "\u201c")
                    and "Roman" in font and size >= SIZE_BODY):
                elems, consumed = self._parse_blockquote(content_lines, i, pn)
                elements.extend(elems)
                i += consumed
                continue

            # Note marker (➠)
            if FONT_DINGBATS in font and "➠" in text:
                note_text = text.replace("➠", "").strip()
                if not note_text and i + 1 < len(content_lines):
                    note_spans = _build_text_spans(content_lines[i + 1])
                    note_text = _spans_plain_text(note_spans).strip()
                    i += 1
                elements.append(DocElement(
                    element_type=ElementType.NOTE, text=note_text, page_number=pn))
                i += 1
                continue

            # Table (header row with aligned Mono keys)
            if self._is_table_header(line):
                table_elem, consumed = self._parse_table(content_lines, i, pn)
                if table_elem:
                    elements.append(table_elem)
                    i += consumed
                    continue

            # Grid table (line-based table from exercise boxes etc.)
            if grid_regions and self._line_in_grid(line, grid_regions):
                grid_elem, consumed = self._parse_grid_table(
                    content_lines, i, grid_regions, pn)
                if grid_elem:
                    elements.append(grid_elem)
                    i += consumed
                    continue

            # Indented note/boxed text (x > X_BODY + 10, not bullet, not heading)
            if x > X_BODY + 15 and not _is_symbol_span(line[0]):
                spans = _build_text_spans(line)
                plain = _spans_plain_text(spans)
                # Check if preceded by a blockquote context (collect as blockquote)
                if elements and elements[-1].element_type == ElementType.BLOCKQUOTE:
                    elements[-1].text += "\n" + plain.strip()
                    i += 1
                    continue
                elements.append(DocElement(
                    element_type=ElementType.BLOCKQUOTE, text=plain.strip(),
                    page_number=pn))
                i += 1
                continue

            # Regular paragraph - collect consecutive same-indent body lines
            all_spans = _build_text_spans(line)
            consumed = 1

            # Merge continuation lines (same x, body size, not structural)
            while i + consumed < len(content_lines):
                nxt = content_lines[i + consumed]
                nxt_x = self._line_x(nxt)
                nxt_size = self._line_size(nxt)
                nxt_font = self._line_font(nxt)
                nxt_text = self._line_text(nxt)

                if nxt_size >= SIZE_SUBSECTION:
                    break
                if FONT_DINGBATS in nxt_font:
                    break
                if _is_symbol_span(nxt[0]) and nxt_text and nxt_text[0] in ("•", "☛", "◦"):
                    break
                if abs(nxt_x - x) > 20:
                    break
                if self._is_table_header(nxt):
                    break
                if callout_boxes and self._line_in_callout(nxt, callout_boxes):
                    break
                # Stop before italic quote lines (blockquotes)
                if _is_italic(nxt[0]["flags"]) and nxt_text and nxt_text[0] in ('"', "\u201c"):
                    break
                # Stop before code blocks (small mono text with light gray color)
                if self._is_code_block_line(nxt):
                    break

                more_spans = _build_text_spans(nxt)
                more_text = _spans_plain_text(more_spans).strip()
                if more_text:
                    prev_text = _spans_plain_text(all_spans)
                    # Handle hyphenation
                    if prev_text.rstrip().endswith("-"):
                        _fix_trailing_hyphen(all_spans)
                    else:
                        all_spans.append(TextSpan(" "))
                    all_spans.extend(more_spans)
                consumed += 1

            plain = _spans_plain_text(all_spans).strip()
            if plain:
                elements.append(DocElement(
                    element_type=ElementType.PARAGRAPH,
                    text=plain, content=all_spans, page_number=pn))
            i += consumed

        return elements

    # ── Helpers ──────────────────────────────────────────────────────

    def _detect_callout_boxes(self, page: fitz.Page) -> list[tuple[float, float]]:
        """Detect LaTeX callout box y-ranges from page drawings with colored fills."""
        boxes: list[tuple[float, float]] = []
        for drawing in page.get_drawings():
            fill = drawing.get("fill")
            if not fill or len(fill) < 3:
                continue
            r, g, b = fill[0], fill[1], fill[2]
            if (r, g, b) in ((1.0, 1.0, 1.0), (0.0, 0.0, 0.0)):
                continue
            rect = drawing["rect"]
            if rect.x1 - rect.x0 > 350:
                boxes.append((rect.y0, rect.y1))
        return sorted(boxes)

    def _line_in_callout(self, line: list[dict], boxes: list[tuple[float, float]]) -> bool:
        """Check if a line's y-coordinate falls inside any callout box."""
        y = line[0]["bbox"][1]
        for y0, y1 in boxes:
            if y0 - 5 <= y <= y1 + 5:
                return True
        return False

    def _parse_callout_box(
        self, lines: list[list[dict]], idx: int,
        boxes: list[tuple[float, float]], pn: int
    ) -> tuple[list[DocElement], int]:
        """Parse all lines within a callout box as a blockquote."""
        parts: list[str] = []
        attribution = ""
        consumed = 0

        first_y = lines[idx][0]["bbox"][1]
        box_y1 = first_y
        for y0, y1 in boxes:
            if y0 - 5 <= first_y <= y1 + 5:
                box_y1 = y1
                break

        for j in range(idx, len(lines)):
            line = lines[j]
            y = line[0]["bbox"][1]
            if y > box_y1 + 5:
                break
            spans = _build_text_spans(line)
            line_text = _spans_plain_text(spans).strip()
            if line_text:
                parts.append(line_text)
            consumed += 1

        if not parts:
            return [], 1

        # Detect attribution: last line is short and looks like a name
        if len(parts) >= 2 and len(parts[-1]) <= 30:
            last = parts[-1].strip()
            if last.startswith("- "):
                attribution = last[2:].strip()
                parts.pop()
            elif last.startswith("— "):
                attribution = last[2:].strip()
                parts.pop()
            elif len(last.split()) <= 3 and "." not in last:
                attribution = last
                parts.pop()
                # Strip trailing dash from quote text
                if parts and parts[-1].rstrip().endswith("-"):
                    parts[-1] = parts[-1].rstrip()[:-1].rstrip()

        return [DocElement(
            element_type=ElementType.BLOCKQUOTE,
            text="\n".join(parts),
            attribution=attribution,
            page_number=pn,
        )], consumed

    def _is_code_block_line(self, line: list[dict]) -> bool:
        """Check if a line looks like a code block (small mono text, light gray)."""
        size = self._line_size(line)
        font = self._line_font(line)
        if not (size < SIZE_BODY and _is_mono(font)):
            return False
        return _color_matches(line[0]["color"], COLOR_LIGHT_GRAY, 0x30)

    def _detect_grid_regions(self, page: fitz.Page) -> list[tuple[float, float]]:
        """Detect table regions from horizontal line grids in page drawings."""
        drawings = page.get_drawings()
        h_lines: list[float] = []
        for d in drawings:
            rect = d["rect"]
            if rect.x1 - rect.x0 > 300 and rect.y1 - rect.y0 < 2:
                # Only black lines are exercise table borders;
                # gray lines (~0.95) are code block borders.
                color = d.get("color")
                if color and max(color) > 0.5:
                    continue
                h_lines.append(rect.y0)

        if len(h_lines) < 3:
            return []

        h_lines.sort()
        tables: list[tuple[float, float]] = []
        start = h_lines[0]
        prev = h_lines[0]
        for y in h_lines[1:]:
            if y - prev > 50:
                if prev - start > 20:
                    tables.append((start, prev))
                start = y
            prev = y
        if prev - start > 20:
            tables.append((start, prev))
        return tables

    def _line_in_grid(self, line: list[dict], regions: list[tuple[float, float]]) -> bool:
        y = line[0]["bbox"][1]
        for y0, y1 in regions:
            if y0 - 2 <= y <= y1 + 2:
                return True
        return False

    def _parse_grid_table(
        self, lines: list[list[dict]], idx: int,
        regions: list[tuple[float, float]], pn: int
    ) -> tuple[DocElement | None, int]:
        """Parse a line-based grid table as a single-column markdown table."""
        first_y = lines[idx][0]["bbox"][1]
        grid_y1 = first_y
        for y0, y1 in regions:
            if y0 - 2 <= first_y <= y1 + 2:
                grid_y1 = y1
                break

        rows: list[list[str]] = []
        consumed = 0

        for j in range(idx, len(lines)):
            line = lines[j]
            y = line[0]["bbox"][1]
            if y > grid_y1 + 5:
                break

            spans = _build_text_spans(line)
            cell = self._render_grid_cell(spans)
            if cell:
                rows.append([cell])
            consumed += 1

        if not rows:
            return None, 1

        return DocElement(element_type=ElementType.TABLE, rows=rows, page_number=pn), consumed

    def _render_grid_cell(self, spans: list[TextSpan]) -> str:
        """Render spans with backtick formatting for mono text."""
        parts: list[str] = []
        for s in spans:
            if s.is_code:
                parts.append(f"`{s.text}`")
            else:
                parts.append(s.text)
        return "".join(parts).strip()

    def _parse_chapter(
        self, lines: list[list[dict]], idx: int, pn: int
    ) -> tuple[list[DocElement], int]:
        elems: list[DocElement] = []
        consumed = 1
        text = self._line_text(lines[idx])
        elems.append(DocElement(
            element_type=ElementType.CHAPTER_HEADING, text=text, page_number=pn))

        if idx + 1 < len(lines):
            nxt_size = self._line_size(lines[idx + 1])
            nxt_text = self._line_text(lines[idx + 1])
            if nxt_size >= SIZE_CHAPTER and nxt_text:
                elems.append(DocElement(
                    element_type=ElementType.CHAPTER_HEADING,
                    text=nxt_text, page_number=pn))
                consumed = 2

        return elems, consumed

    def _heading_after_bullet(self, line: list[dict]) -> str:
        """Extract heading text from a line starting with a Dingbats bullet."""
        content = [s for s in line if not _is_symbol_span(s)]
        return _spans_to_line_text(content).strip()

    def _parse_practice(
        self, lines: list[list[dict]], idx: int,
        practice_type: ElementType, pn: int
    ) -> tuple[list[DocElement], int]:
        consumed = 1
        content_parts: list[str] = []

        header_spans = [s for s in lines[idx] if FONT_DINGBATS not in s.get("font", "")]
        header_text = _spans_to_line_text(header_spans).strip()

        for j in range(idx + 1, len(lines)):
            line = lines[j]
            size = self._line_size(line)
            font = self._line_font(line)
            text = self._line_text(line)

            if size >= SIZE_SUBSECTION:
                break
            if FONT_DINGBATS in font and any(c in text for c in ("✓", "✗", "●", "☛")):
                break
            if text and _is_symbol_span(line[0]) and text[0] in ("•", "☛", "◦"):
                break

            spans = _build_text_spans(line)
            line_text = _spans_plain_text(spans).strip()
            if line_text:
                content_parts.append(line_text)
            consumed += 1

        return [
            DocElement(element_type=practice_type, text=header_text, page_number=pn),
            DocElement(element_type=ElementType.BLOCKQUOTE,
                       text="\n".join(content_parts), page_number=pn),
        ], consumed

    def _collect_code_block(
        self, lines: list[list[dict]], idx: int
    ) -> tuple[list[str], int]:
        code_lines: list[str] = []
        consumed = 0
        for j in range(idx, len(lines)):
            line = lines[j]
            if not self._is_code_block_line(line):
                break
            code_lines.append(_spans_to_line_text(line).strip())
            consumed += 1
        return code_lines, consumed

    def _parse_blockquote(
        self, lines: list[list[dict]], idx: int, pn: int
    ) -> tuple[list[DocElement], int]:
        consumed = 0
        quote_parts: list[str] = []
        attribution = ""

        for j in range(idx, len(lines)):
            line = lines[j]
            text = self._line_text(line)
            if not text:
                consumed += 1
                continue

            # Attribution: starts with — (em dash)
            if text.startswith("—"):
                attribution = text.lstrip("—").strip()
                consumed += 1
                break

            size = self._line_size(line)
            font = self._line_font(line)
            if not _is_italic(line[0]["flags"]) and "Roman" in font and size >= SIZE_BODY:
                if not text.startswith("—"):
                    break

            spans = _build_text_spans(line)
            line_text = _spans_plain_text(spans).strip()
            if line_text:
                quote_parts.append(line_text)
            consumed += 1

        return [DocElement(
            element_type=ElementType.BLOCKQUOTE,
            text="\n".join(quote_parts),
            attribution=attribution, page_number=pn,
        )], consumed

    def _is_table_header(self, line: list[dict]) -> bool:
        """Detect table header: has spans aligned at 3+ distinct x-positions with Mono keys."""
        if len(line) < 4:
            return False
        mono_count = sum(1 for s in line if _is_mono(s.get("font", "")))
        if mono_count < 2:
            return False
        # Check for 3+ distinct x-positions (columns)
        xs = sorted(set(round(s["bbox"][0]) for s in line))
        # Cluster nearby x-positions
        clusters: list[int] = [xs[0]]
        for x in xs[1:]:
            if x - clusters[-1] > 10:
                clusters.append(x)
        return len(clusters) >= 3

    def _parse_table(
        self, lines: list[list[dict]], idx: int, pn: int
    ) -> tuple[DocElement | None, int]:
        """Parse a markdown table from consecutive aligned lines."""
        first = lines[idx]

        # Detect column boundaries from header
        col_xs = self._detect_columns(first)
        if len(col_xs) < 2:
            return None, 1

        num_cols = len(col_xs)
        rows: list[list[str]] = []
        consumed = 0

        for j in range(idx, len(lines)):
            line = lines[j]
            text = self._line_text(line)
            if not text:
                consumed += 1
                continue

            # Check if line still has table-like structure
            line_cols = self._detect_columns(line)
            if len(line_cols) < num_cols - 1:
                break

            cells = self._extract_table_row(line, col_xs, num_cols)
            rows.append(cells)
            consumed += 1

        if not rows:
            return None, 1
        return DocElement(
            element_type=ElementType.TABLE, rows=rows, page_number=pn), consumed

    def _detect_columns(self, line: list[dict]) -> list[float]:
        """Detect column x-positions from a line's spans."""
        xs = sorted(set(round(s["bbox"][0]) for s in line))
        clusters: list[float] = [xs[0]]
        for x in xs[1:]:
            if x - clusters[-1] > 10:
                clusters.append(float(x))
        return clusters

    def _extract_table_row(
        self, line: list[dict], col_xs: list[float], num_cols: int
    ) -> list[str]:
        """Extract cells from a table row using column positions."""
        cells: list[list[str]] = [[] for _ in range(num_cols)]

        for span in line:
            sx = span["bbox"][0]
            # Find nearest column
            best_col = 0
            best_dist = float("inf")
            for ci, cx in enumerate(col_xs):
                dist = abs(sx - cx)
                if dist < best_dist:
                    best_dist = dist
                    best_col = ci
            if best_col < num_cols:
                cells[best_col].append(span["text"])

        return [" ".join(cell).strip() for cell in cells]
