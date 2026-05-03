"""Convert Document model to Markdown string."""

from __future__ import annotations

import re

from .models import DocElement, Document, ElementType, TextSpan

_LIST_TYPES = frozenset({
    ElementType.BULLET_ITEM, ElementType.SUB_BULLET_ITEM, ElementType.TOC_ENTRY,
})


class MarkdownRenderer:
    def __init__(self) -> None:
        self._toc_counter = 0
        self._toc_sub_counter = 0
        self._in_toc = False

    def render(self, document: Document) -> str:
        parts: list[tuple[str, ElementType]] = []
        for element in document.elements:
            md = self._render_element(element)
            if md:
                parts.append((md, element.element_type))

        if not parts:
            return ""

        lines: list[str] = [parts[0][0]]
        for i in range(1, len(parts)):
            prev_type = parts[i - 1][1]
            curr_type = parts[i][1]
            if prev_type in _LIST_TYPES and curr_type in _LIST_TYPES:
                lines.append(parts[i][0])
            else:
                lines.append("")
                lines.append(parts[i][0])

        result = "\n".join(lines)
        result = re.sub(r"\n{3,}", "\n\n", result)
        return result.strip() + "\n"

    def _render_element(self, element: DocElement) -> str:
        et = element.element_type

        if et == ElementType.TITLE:
            return f"# {element.text}"

        if et == ElementType.SUBTITLE:
            return f"## {element.text}"

        if et == ElementType.SUMMARY:
            return f"*{element.text}*"

        if et == ElementType.HORIZONTAL_RULE:
            return "---"

        if et == ElementType.TABLE_OF_CONTENTS:
            self._in_toc = True
            self._toc_counter = 0
            self._toc_sub_counter = 0
            return f"# {element.text}"

        if et == ElementType.TOC_ENTRY:
            return self._render_toc_entry(element)

        if et == ElementType.CHAPTER_HEADING:
            return f"## {element.text}"

        if et == ElementType.SECTION_HEADING:
            return f"### {element.text}"

        if et == ElementType.SUBSECTION_HEADING:
            return f"### {element.text}"

        if et == ElementType.PARAGRAPH:
            return self._render_paragraph(element)

        if et == ElementType.BULLET_ITEM:
            text = self._render_spans(element.content) or element.text
            return f"- {text}"

        if et == ElementType.SUB_BULLET_ITEM:
            text = self._render_spans(element.content) or element.text
            return f"    - {text}"

        if et == ElementType.BLOCKQUOTE:
            return self._render_blockquote(element)

        if et == ElementType.GOOD_PRACTICE:
            return f"#### {element.text}"

        if et == ElementType.BAD_PRACTICE:
            return f"#### {element.text}"

        if et == ElementType.CODE_BLOCK:
            return self._render_code_block(element)

        if et == ElementType.TABLE:
            return self._render_table(element)

        if et == ElementType.NOTE:
            return f"*{element.text}*"

        if et == ElementType.IMAGE:
            return f"![{element.text}]({element.text})"

        return ""

    def _render_toc_entry(self, element: DocElement) -> str:
        text = element.text
        clean = _strip_toc_prefix(text)
        if element.level == 0:
            self._toc_counter += 1
            self._toc_sub_counter = 0
            return f"{self._toc_counter}. {clean}"
        else:
            self._toc_sub_counter += 1
            return f"    {self._toc_sub_counter}. {clean}"

    def _render_paragraph(self, element: DocElement) -> str:
        if element.content:
            text = self._render_spans(element.content)
        else:
            text = element.text
        return text

    def _render_spans(self, spans: list[TextSpan]) -> str:
        parts: list[str] = []
        for span in spans:
            text = span.text
            if not text:
                continue
            if span.is_code:
                core = text.strip()
                if core:
                    parts.append(f"`{core}`")
            elif span.is_bold and span.is_italic:
                core = text.strip()
                if core:
                    lead = text[:len(text) - len(text.lstrip())]
                    trail = text[len(text.rstrip()):]
                    parts.append(f"{lead}***{core}***{trail}")
            elif span.is_bold:
                core = text.strip()
                if core:
                    lead = text[:len(text) - len(text.lstrip())]
                    trail = text[len(text.rstrip()):]
                    parts.append(f"{lead}**{core}**{trail}")
            elif span.is_italic:
                core = text.strip()
                if core:
                    lead = text[:len(text) - len(text.lstrip())]
                    trail = text[len(text.rstrip()):]
                    parts.append(f"{lead}*{core}*{trail}")
            else:
                parts.append(text)
        return "".join(parts)

    def _render_blockquote(self, element: DocElement) -> str:
        lines = element.text.split("\n")
        parts: list[str] = []

        for line in lines:
            if line.strip():
                parts.append(f"> {line.strip()}")

        if element.attribution:
            parts.append(">")
            parts.append(f"> -- {element.attribution}")

        return "\n".join(parts)

    def _render_code_block(self, element: DocElement) -> str:
        lang = element.language or ""
        return f"```{lang}\n{element.text}\n```"

    def _render_table(self, element: DocElement) -> str:
        if not element.rows:
            return ""

        num_cols = max(len(row) for row in element.rows) if element.rows else 0
        if num_cols == 0:
            return ""

        lines: list[str] = []

        header = element.rows[0] + [""] * (num_cols - len(element.rows[0]))
        lines.append("| " + " | ".join(header[:num_cols]) + " |")
        lines.append("| " + " | ".join("---" for _ in range(num_cols)) + " |")

        for row in element.rows[1:]:
            padded = row + [""] * (num_cols - len(row))
            lines.append("| " + " | ".join(padded[:num_cols]) + " |")

        return "\n".join(lines)


def _strip_toc_prefix(text: str) -> str:
    """Strip Roman numeral or numbered prefix from TOC entries."""
    match = re.match(r"^(?:[IVX]+\.?\d*\s+)(.*)", text)
    if match:
        return match.group(1)
    return text
