"""Wrapper around legacy `section_parser` providing BillHierarchy tree API."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List
import logging

# Import legacy section_parser on-demand
from importlib import import_module, util as _import_util, machinery as _import_mach

try:
    _section_mod = import_module("section_parser.section_parser")
except ModuleNotFoundError:
    _path = "/mnt/data/AI4Deliberation/section_parser/section_parser.py"
    spec = _import_util.spec_from_file_location("_section_parser_fallback", _path)
    _section_mod = _import_util.module_from_spec(spec)  # type: ignore
    loader: _import_mach.SourceFileLoader = spec.loader  # type: ignore
    loader.exec_module(_section_mod)  # type: ignore

logger = logging.getLogger(__name__)

__all__ = ["Article", "Chapter", "Part", "BillHierarchy"]


@dataclass
class Article:
    id: int
    title: str
    text: str
    chapter: "Chapter" | None = field(repr=False, default=None)

    @property
    def words(self) -> int:
        return len(self.text.split())


@dataclass
class Chapter:
    name: str  # Greek numeral (e.g., "Α'")
    articles: List[Article] = field(default_factory=list)
    part: "Part" | None = field(repr=False, default=None)

    def iter_text(self) -> str:
        return "\n\n".join(a.text for a in self.articles)


@dataclass
class Part:
    name: str  # Greek numeral with prime mark
    chapters: List[Chapter] = field(default_factory=list)

    def iter_text(self) -> str:
        return "\n\n".join(ch.iter_text() for ch in self.chapters)


@dataclass
class BillHierarchy:
    parts: List[Part]

    # ------------------------------------------------------------------
    # Factory ------------------------------------------------------------------
    # ------------------------------------------------------------------
    @classmethod
    def from_db_rows(cls, rows):
        """Build hierarchy tree from rows provided by `section_parser.parse_titles`."""
        # Expect rows sorted by id ascending
        part_map = {}
        chapter_map = {}
        parts: List[Part] = []

        for r in rows:
            part_name = r.get("part")
            chap_name = r.get("chapter")

            # Part node
            if part_name and part_name not in part_map:
                p = Part(name=part_name)
                part_map[part_name] = p
                parts.append(p)
            part_node = part_map.get(part_name) if part_name else None

            # Chapter node
            if chap_name:
                key = (part_name, chap_name)
                if key not in chapter_map:
                    ch = Chapter(name=chap_name, part=part_node)
                    chapter_map[key] = ch
                    if part_node:
                        part_node.chapters.append(ch)
                ch_node = chapter_map[key]
            else:
                ch_node = None

            # Article
            a = Article(id=r["id"], title=r["title"], text=r.get("content", ""), chapter=ch_node)
            if ch_node:
                ch_node.articles.append(a)
            elif part_node:
                # Chapterless article inside part
                if not hasattr(part_node, "misc_articles"):
                    part_node.misc_articles: List[Article] = []  # type: ignore
                part_node.misc_articles.append(a)
            else:
                logger.warning("Article id %s has no Part/Chapter", r["id"])

        return cls(parts=parts)
