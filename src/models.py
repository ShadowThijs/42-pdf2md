"""Data model for the intermediate document representation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto


class ElementType(Enum):
    TITLE = auto()
    SUBTITLE = auto()
    SUMMARY = auto()
    HORIZONTAL_RULE = auto()
    TABLE_OF_CONTENTS = auto()
    TOC_ENTRY = auto()
    CHAPTER_HEADING = auto()
    SECTION_HEADING = auto()
    SUBSECTION_HEADING = auto()
    PARAGRAPH = auto()
    BULLET_ITEM = auto()
    SUB_BULLET_ITEM = auto()
    BLOCKQUOTE = auto()
    GOOD_PRACTICE = auto()
    BAD_PRACTICE = auto()
    CODE_BLOCK = auto()
    TABLE = auto()
    IMAGE = auto()
    NOTE = auto()


@dataclass
class TextSpan:
    """A run of text with formatting."""
    text: str
    is_bold: bool = False
    is_italic: bool = False
    is_code: bool = False


@dataclass
class DocElement:
    """A semantic element in the document."""
    element_type: ElementType
    content: list[TextSpan] = field(default_factory=list)
    level: int = 0
    text: str = ""
    rows: list[list[str]] = field(default_factory=list)
    language: str = ""
    attribution: str = ""
    page_number: int = 0


@dataclass
class Document:
    """Top-level document model."""
    elements: list[DocElement] = field(default_factory=list)
