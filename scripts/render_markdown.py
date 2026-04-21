#!/usr/bin/env python3
"""Markdown → HWPX 서식 렌더러.

`dump_markdown.py` 가 평문 덤프라면 이 스크립트는 Markdown 문법을
해석해 HWPX 의 제목 스타일·리스트·코드·표·링크·이미지까지 반영한다.
파서는 CommonMark 호환 `markdown-it-py` 를 쓰고, HWPX 쪽은
python-hwpx 의 `HwpxDocument` 고수준 API + 필요한 곳만 저수준 XML 을
사용한다.

사용법::

    python render_markdown.py INPUT.md [OUTPUT.hwpx]
    cat notes.md | python render_markdown.py - notes.hwpx

지원 범위는 단계적으로 확장된다:

* T1 — 제목(h1~h6) 스타일, 불릿/순서 리스트(중첩 포함), 코드 블록,
  수평선, 빈 단락
* T2 — 인라인 `**굵게**` / `*기울임*` / ``인라인코드`` 런, 표 렌더링
* T3 — 링크, 이미지 임베딩, 블록 인용, 구문 강조 코드 블록, 체크박스

OUTPUT 을 생략하면 `<INPUT stem>.hwpx` 를 CWD 에 쓴다. INPUT 이
``-`` 이면 stdin 을 읽고 기본 출력명은 ``stdin.hwpx`` 가 된다.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

try:
    from hwpx.document import HwpxDocument
except ImportError:  # pragma: no cover
    sys.stderr.write("error: python-hwpx 가 설치되지 않았습니다.\n")
    raise SystemExit(1)

try:
    from markdown_it import MarkdownIt
except ImportError:  # pragma: no cover
    sys.stderr.write(
        "error: markdown-it-py 가 설치되지 않았습니다. "
        "`pip install markdown-it-py` 로 먼저 설치하세요.\n"
    )
    raise SystemExit(1)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hwpx_toolkit import normalize_namespaces_in_place  # noqa: E402


# --------------------------------------------------------------------------- #
# 스타일 ID 조회                                                              #
# --------------------------------------------------------------------------- #

# `HwpxDocument.new()` 의 기본 템플릿에는 "바탕글", "본문", "개요 1~10",
# "머리말", "각주", "차례 1~3", "캡션" 같은 스타일이 이미 정의돼 있다.
# Markdown 의 제목 레벨(1~6)을 개요 스타일로 매핑한다.
HEADING_STYLE_NAMES = {
    1: "개요 1",
    2: "개요 2",
    3: "개요 3",
    4: "개요 4",
    5: "개요 5",
    6: "개요 6",
}
BODY_STYLE_NAME = "바탕글"


def _style_id_by_name(doc: HwpxDocument, name: str) -> str | None:
    for sid, style in doc.styles.items():
        if getattr(style, "name", None) == name:
            return str(sid)
    return None


# --------------------------------------------------------------------------- #
# 리스트 마커                                                                 #
# --------------------------------------------------------------------------- #

BULLET_CHARS = ("•", "◦", "▪", "▫")  # depth 0, 1, 2, 3+
LIST_INDENT = "  "  # 공백 2 칸씩 들여쓰기 — 저수준 intent 설정 없이 간이 표현


def _bullet_for_depth(depth: int) -> str:
    return BULLET_CHARS[min(depth, len(BULLET_CHARS) - 1)]


# --------------------------------------------------------------------------- #
# 렌더러                                                                      #
# --------------------------------------------------------------------------- #


class MarkdownHwpxRenderer:
    """markdown-it-py 토큰 스트림 → HwpxDocument 상태 머신."""

    def __init__(self, doc: HwpxDocument) -> None:
        self.doc = doc
        self.body_style = _style_id_by_name(doc, BODY_STYLE_NAME)
        self.heading_styles = {
            lvl: _style_id_by_name(doc, name)
            for lvl, name in HEADING_STYLE_NAMES.items()
        }
        # 리스트 상태: 스택 기반으로 중첩 추적
        # 각 항목: ("bullet", depth) 또는 ("ordered", depth, next_number)
        self.list_stack: list = []

    # ---- 공개 진입점 ---- #

    def render(self, markdown_text: str) -> None:
        md = MarkdownIt("commonmark").enable("table")
        tokens = md.parse(markdown_text)
        self._render_tokens(tokens)

    # ---- 내부 로직 ---- #

    def _add_para(self, text: str, *, style_id: str | None = None) -> None:
        kwargs = {}
        if style_id is not None:
            kwargs["style_id_ref"] = style_id
        self.doc.add_paragraph(text, **kwargs)

    def _current_list_prefix(self) -> str:
        """현재 리스트 스택 상태에서 사용할 들여쓰기 + 마커 문자열."""
        if not self.list_stack:
            return ""
        frame = self.list_stack[-1]
        depth = frame[1]
        indent = LIST_INDENT * depth
        if frame[0] == "ordered":
            num = frame[2]
            return f"{indent}{num}. "
        return f"{indent}{_bullet_for_depth(depth)} "

    def _bump_list_counter(self) -> None:
        if self.list_stack and self.list_stack[-1][0] == "ordered":
            kind, depth, num = self.list_stack[-1]
            self.list_stack[-1] = (kind, depth, num + 1)

    def _render_tokens(self, tokens: list) -> None:
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            t = tok.type

            if t == "heading_open":
                level = int(tok.tag[1:])  # 'h1' → 1
                inline = tokens[i + 1]
                style = self.heading_styles.get(level) or self.body_style
                self._add_para(inline.content, style_id=style)
                i += 3
                continue

            if t == "paragraph_open":
                inline = tokens[i + 1]
                text = self._current_list_prefix() + inline.content
                self._add_para(text, style_id=self.body_style)
                i += 3
                continue

            if t == "bullet_list_open":
                depth = sum(1 for f in self.list_stack if True)
                self.list_stack.append(("bullet", depth))
                i += 1
                continue

            if t == "ordered_list_open":
                depth = sum(1 for f in self.list_stack if True)
                start = int(tok.attrGet("start") or 1)
                self.list_stack.append(("ordered", depth, start))
                i += 1
                continue

            if t in ("bullet_list_close", "ordered_list_close"):
                if self.list_stack:
                    self.list_stack.pop()
                i += 1
                continue

            if t == "list_item_open":
                # 마커만 준비 — 뒤따라오는 paragraph_open 이 본문을 낸다.
                i += 1
                continue

            if t == "list_item_close":
                self._bump_list_counter()
                i += 1
                continue

            if t == "fence" or t == "code_block":
                lang = (tok.info or "").strip()
                if lang:
                    self._add_para(f"```{lang}", style_id=self.body_style)
                else:
                    self._add_para("```", style_id=self.body_style)
                for line in tok.content.splitlines() or [""]:
                    self._add_para(line, style_id=self.body_style)
                self._add_para("```", style_id=self.body_style)
                i += 1
                continue

            if t == "hr":
                self._add_para("─" * 40, style_id=self.body_style)
                i += 1
                continue

            if t == "blockquote_open":
                # T1 에서는 "> " 접두어로만 표시. T3 에서 들여쓰기·테두리.
                depth = sum(1 for f in self.list_stack if True)
                self.list_stack.append(("blockquote", depth))
                i += 1
                continue

            if t == "blockquote_close":
                if self.list_stack and self.list_stack[-1][0] == "blockquote":
                    self.list_stack.pop()
                i += 1
                continue

            if t == "table_open":
                # T2 에서 구현. T1 에서는 원문 텍스트로 일단 덤프.
                j = i + 1
                while j < len(tokens) and tokens[j].type != "table_close":
                    j += 1
                self._add_para("[표: T2 에서 렌더링 예정]", style_id=self.body_style)
                i = j + 1
                continue

            # 기타 블록 (html_block 등) — 원문을 단락으로
            if hasattr(tok, "content") and tok.content:
                for line in tok.content.splitlines():
                    self._add_para(line, style_id=self.body_style)
            i += 1


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #


def _read_source(token: str) -> tuple[str, str]:
    if token == "-":
        return sys.stdin.read(), "stdin"
    src = Path(token)
    if not src.exists():
        raise FileNotFoundError(f"input not found: {src}")
    return src.read_text(encoding="utf-8"), src.stem


def render_file(text: str, output: Path) -> Path:
    doc = HwpxDocument.new()
    renderer = MarkdownHwpxRenderer(doc)
    renderer.render(text)
    output.parent.mkdir(parents=True, exist_ok=True)
    doc.save_to_path(str(output))
    normalize_namespaces_in_place(str(output))
    return output


def _run(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        sys.stderr.write("Usage: python render_markdown.py INPUT.md [OUTPUT.hwpx]\n")
        return 2
    try:
        text, default_stem = _read_source(argv[1])
    except FileNotFoundError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    output = Path(argv[2]) if len(argv) == 3 else Path.cwd() / f"{default_stem}.hwpx"
    try:
        written = render_file(text, output)
    except Exception as exc:  # noqa: BLE001 — CLI surface
        sys.stderr.write(f"error: {exc}\n")
        return 1
    sys.stdout.write(f"ok: {written} ({written.stat().st_size} bytes)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run(sys.argv))
