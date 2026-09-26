"""Structured rows for table blocks (spec section 4 step 5; ADR 0030).

The page parser writes a table as one ``table`` block whose text holds the rows
as lines with cells separated by ``" | "`` (``page_parse`` v1/v2). This module
turns that text back into rows, deterministically and without a model: pipe
rows (with or without Markdown borders and ``---`` separator lines), tab
separated rows, or columns split by runs of two or more spaces. Text that does
not look tabular (fewer than two columns in most rows) is not a table.

CSV and HTML are derived from the rows. The HTML escapes every cell, so it is
safe to store; the web reader still renders from ``rows``, never raw HTML.
"""

from __future__ import annotations

import csv
import html
import io
import re
from dataclasses import dataclass

MAX_ROWS = 500
MAX_COLS = 30
MAX_CELL = 500
_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_SPACES = re.compile(r"\s{2,}")


@dataclass(frozen=True, slots=True)
class Table:
    rows: list[list[str]]
    header: bool

    @property
    def n_rows(self) -> int:
        return len(self.rows)

    @property
    def n_cols(self) -> int:
        return max((len(r) for r in self.rows), default=0)


def _cells(line: str) -> list[str]:
    if "|" in line:
        parts = line.strip().split("|")
        if parts and not parts[0].strip():
            parts = parts[1:]
        if parts and not parts[-1].strip():
            parts = parts[:-1]
        return [p.strip() for p in parts]
    if "\t" in line:
        return [p.strip() for p in line.split("\t")]
    return [p.strip() for p in _SPACES.split(line.strip())]


def parse_table(text: str) -> Table | None:
    """Rows of a table block, or None when the text is not tabular."""
    lines = [line for line in text.splitlines() if line.strip()]
    had_separator = any(_SEPARATOR.match(line) for line in lines)
    rows = [_cells(line) for line in lines if not _SEPARATOR.match(line)]
    rows = [[cell[:MAX_CELL] for cell in row][:MAX_COLS] for row in rows[:MAX_ROWS]]
    if not rows:
        return None
    multi = sum(1 for row in rows if len(row) >= 2)
    if multi == 0 or multi * 2 < len(rows):
        return None
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]
    return Table(rows=padded, header=len(padded) >= 2 or had_separator)


def to_csv(table: Table) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerows(table.rows)
    return out.getvalue()


def to_html(table: Table) -> str:
    """Escaped HTML; the first row is the header when ``table.header``."""
    def row(cells: list[str], tag: str) -> str:
        inner = "".join(f"<{tag}>{html.escape(cell)}</{tag}>" for cell in cells)
        return f"<tr>{inner}</tr>"

    body = table.rows[1:] if table.header else table.rows
    head = f"<thead>{row(table.rows[0], 'th')}</thead>" if table.header else ""
    return f"<table>{head}<tbody>{''.join(row(r, 'td') for r in body)}</tbody></table>"


def plain_text(table: Table) -> str:
    """Searchable text: one line per row, cells separated by ' | '."""
    return "\n".join(" | ".join(cell for cell in row if cell) for row in table.rows)
