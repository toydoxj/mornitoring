"""의견상세 저장 전 텍스트 정리 도우미."""

from __future__ import annotations

import re
from typing import Any


_SOURCE_PAGE_PARENS_RE = re.compile(
    r"\(\s*(?:구조계산서|구조도면)\s*[:：]?\s*[^()]*?\b(?:page|p\.|페이지)\b[^()]*?\)",
    re.IGNORECASE,
)
_ATTACHED_SOURCE_PAGE_RE = re.compile(
    r"(?:구조계산서|구조도면)\s*[:：]?\s*"
    r"(?:page|p\.|페이지)\s*[:.]?\s*"
    r"\d+\s*(?:[~\-]\s*\d+)?(?:\s*,\s*\d+\s*(?:[~\-]\s*\d+)?)*",
    re.IGNORECASE,
)
_COMMA_DOCUMENT_TOKEN_RE = re.compile(
    r"(?:(?<=^)|(?<=,))\s*[\"'“”‘’]?\s*(?:구조계산서|구조도면)\s*[\"'“”‘’]?\s*(?=,|$)"
)
_NUMBER_PAGE_RE = re.compile(
    r"(?<![A-Za-z0-9가-힣])"
    r"\d+\s*(?:[~\-]\s*\d+)?(?:\s*,\s*\d+\s*(?:[~\-]\s*\d+)?)*"
    r"\s*(?:page|p\.|페이지)"
    r"(?![A-Za-z0-9가-힣])",
    re.IGNORECASE,
)
_LABEL_PAGE_RE = re.compile(
    r"(?<![A-Za-z0-9가-힣])(?:page|p\.|페이지)\s*[:.]?\s*"
    r"\d+\s*(?:[~\-]\s*\d+)?(?:\s*,\s*\d+\s*(?:[~\-]\s*\d+)?)*"
    r"(?![A-Za-z0-9가-힣])",
    re.IGNORECASE,
)
_STANDALONE_PAGE_RE = re.compile(
    r"(?<![A-Za-z0-9가-힣])(?:page|p\.|페이지)(?![A-Za-z0-9가-힣])",
    re.IGNORECASE,
)


def clean_opinion_detail_content(value: Any) -> str:
    """의견상세 본문에서 출처용 문서명/PAGE 표기만 제거한다."""
    if value is None:
        return ""

    text = str(value).strip()
    if not text:
        return ""

    text = text.replace("_x000D_", "\n").replace("_x000d_", "\n").replace("\r", "\n")
    text = _SOURCE_PAGE_PARENS_RE.sub("", text)
    text = _ATTACHED_SOURCE_PAGE_RE.sub("", text)
    text = _COMMA_DOCUMENT_TOKEN_RE.sub("", text)
    text = _NUMBER_PAGE_RE.sub("", text)
    text = _LABEL_PAGE_RE.sub("", text)
    text = _STANDALONE_PAGE_RE.sub("", text)
    text = _COMMA_DOCUMENT_TOKEN_RE.sub("", text)

    text = re.sub(r"(?:\s*,\s*){2,}", ", ", text)
    text = re.sub(r"\(\s*,\s*", "(", text)
    text = re.sub(r"\s*,\s*\)", ")", text)
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"\s+([,.)])", r"\1", text)
    text = re.sub(r"([(])\s+", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"^\s*,\s*", "", text)
    text = re.sub(r"\s*,\s*$", "", text)
    return text.strip()
