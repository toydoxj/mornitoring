"""검토서 상세의견/심각도 파서."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


SEVERITY_LABELS = ("L0", "L1", "L2", "L3", "L4")


@dataclass
class OpinionEntry:
    row: int
    section: str
    severity: str
    content: str


@dataclass
class OpinionParseResult:
    formatted_text: str | None = None
    severity_counts: dict[str, int] = field(
        default_factory=lambda: {label: 0 for label in SEVERITY_LABELS}
    )
    errors: list[str] = field(default_factory=list)
    entries: list[OpinionEntry] = field(default_factory=list)


def clean_cell_text(value: Any) -> str:
    """엑셀 셀 값을 사람이 읽기 좋은 단일 문자열로 정리."""
    if value is None:
        return ""
    text = str(value).strip()
    text = text.replace("_x000D_", "\n").replace("_x000d_", "\n").replace("\r", "\n")
    return re.sub(r"\s+", " ", text).strip()


def normalize_severity(value: Any) -> str | None:
    """0~4, L0~L4 값을 표준 L0~L4 라벨로 변환."""
    text = clean_cell_text(value).upper().replace(" ", "")
    if not text:
        return None
    if re.fullmatch(r"L[0-4]", text):
        return text
    if re.fullmatch(r"[0-4]", text):
        return f"L{text}"
    return None


def _strip_numbering(text: str) -> str:
    text = re.sub(r"^\s*\d+\s*[.)．]?\s*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _section_title(section: str, subsection: str | None) -> str:
    section = _strip_numbering(section)
    subsection = _strip_numbering(subsection or "")
    section_map = {
        "하중 적정성": "하중의 적정성",
        "부재 설계 적정성": "부재설계의 적정성",
        "구조도면 작성 적정성": "구조도면 작성의 적정성",
    }
    section = section_map.get(section, section)
    if section == "기타의견":
        return section
    return f"{section} - {subsection}" if subsection else section


def _find_detail_header_row(ws) -> int:
    for row in range(1, min(ws.max_row, 120) + 1):
        detail_label = clean_cell_text(ws.cell(row=row, column=4).value)
        severity_label = clean_cell_text(ws.cell(row=row, column=8).value)
        if "상세의견" in detail_label and "심각도" in severity_label:
            return row
    return 17


def _find_detail_end_row(ws, start_row: int) -> int:
    for row in range(start_row + 1, min(ws.max_row, 140) + 1):
        label = clean_cell_text(ws.cell(row=row, column=2).value)
        if "적정성 검토 결과" in label or "보완서류" in label:
            return row
    return min(ws.max_row, 140) + 1


def parse_review_opinions(ws) -> OpinionParseResult:
    """상세의견 D열과 심각도 H열을 읽어 저장용 텍스트와 집계를 만든다."""
    result = OpinionParseResult()
    header_row = _find_detail_header_row(ws)
    end_row = _find_detail_end_row(ws, header_row)
    current_section = ""
    current_subsection = ""

    for row in range(header_row + 1, end_row):
        section = clean_cell_text(ws.cell(row=row, column=2).value)
        subsection = clean_cell_text(ws.cell(row=row, column=3).value)
        if section:
            current_section = section
        if subsection:
            current_subsection = subsection

        content = clean_cell_text(ws.cell(row=row, column=4).value)
        if not content:
            continue

        severity = normalize_severity(ws.cell(row=row, column=8).value)
        if severity is None:
            result.errors.append(
                f"상세의견이 입력된 {row}행의 심각도(H{row})가 비어 있거나 올바르지 않습니다. "
                "0~4 또는 L0~L4 중 하나를 입력해주세요."
            )
            continue

        title = _section_title(current_section or "상세의견", current_subsection)
        result.severity_counts[severity] += 1
        result.entries.append(OpinionEntry(
            row=row,
            section=title,
            severity=severity,
            content=content,
        ))

    if result.entries:
        grouped: dict[str, list[OpinionEntry]] = {}
        for entry in result.entries:
            grouped.setdefault(entry.section, []).append(entry)

        blocks = []
        for section, entries in grouped.items():
            lines = [f"[{section}]"]
            lines.extend(f"{{{entry.severity}}} {entry.content}" for entry in entries)
            blocks.append("\n".join(lines))
        result.formatted_text = "\n\n".join(blocks)

    return result
