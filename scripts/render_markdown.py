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
    import hwpx.oxml.document as _hwpx_oxml  # noqa: F401 — for _HH constant
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

from lxml import etree as _LXML_ET  # python-hwpx 내부와 호환되는 요소 빌더

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hwpx_toolkit import normalize_namespaces_in_place  # noqa: E402


_HH = _hwpx_oxml._HH  # "{http://www.hancom.co.kr/hwpml/2011/head}"


# --------------------------------------------------------------------------- #
# 스타일 ID 조회 / 생성                                                       #
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


def _char_style_flags(element) -> tuple[bool, bool, bool]:
    """(bold, italic, underline-active) 플래그 추출."""
    bold = element.find(f"{_HH}bold") is not None
    italic = element.find(f"{_HH}italic") is not None
    underline_el = element.find(f"{_HH}underline")
    underline = (
        underline_el is not None
        and (underline_el.get("type") or "").upper() != "NONE"
    )
    return bold, italic, underline


def _ensure_char_style(
    doc: HwpxDocument,
    *,
    bold: bool = False,
    italic: bool = False,
    underline: bool = False,
) -> str:
    """Bold/Italic/Underline 조합에 맞는 charPr 를 찾거나 새로 만들고 id 반환.

    python-hwpx 2.9.0 의 `ensure_run_style` 은 stdlib ``ElementTree.SubElement``
    와 ``lxml`` 요소를 섞어 쓰다가 ``TypeError`` 로 크래시한다. 우리는
    `header.ensure_char_property` 를 직접 호출하고 modifier 를 lxml 기반으로
    작성해서 우회한다.
    """
    header = doc.headers[0]
    target = (bool(bold), bool(italic), bool(underline))

    def predicate(el) -> bool:
        return _char_style_flags(el) == target

    def modifier(el) -> None:
        # 기존 bold/italic 마커 제거
        for tag in ("bold", "italic"):
            for child in list(el.findall(f"{_HH}{tag}")):
                el.remove(child)
        # underline 은 항상 존재하는 구조라 type 만 교체
        underline_nodes = list(el.findall(f"{_HH}underline"))
        base_underline_attrs = (
            dict(underline_nodes[0].attrib) if underline_nodes else {}
        )
        for node in underline_nodes:
            el.remove(node)

        if bold:
            _LXML_ET.SubElement(el, f"{_HH}bold")
        if italic:
            _LXML_ET.SubElement(el, f"{_HH}italic")

        ul_attrs = dict(base_underline_attrs)
        ul_attrs["type"] = "SOLID" if underline else "NONE"
        ul_attrs.setdefault("shape", "SOLID")
        ul_attrs.setdefault("color", "#000000")
        _LXML_ET.SubElement(el, f"{_HH}underline", ul_attrs)

    new_el = header.ensure_char_property(
        predicate=predicate,
        modifier=modifier,
        base_char_pr_id="0",
    )
    return new_el.get("id")


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
        # 인라인 런 스타일 — 문서 생성 시 1 회만 만든다.
        self.cp_regular = _ensure_char_style(doc)
        self.cp_bold = _ensure_char_style(doc, bold=True)
        self.cp_italic = _ensure_char_style(doc, italic=True)
        self.cp_bold_italic = _ensure_char_style(doc, bold=True, italic=True)
        self.cp_underline = _ensure_char_style(doc, underline=True)
        # 리스트 상태: 스택 기반 중첩 추적
        # 각 항목: ("bullet", depth) / ("ordered", depth, next_number) / ("blockquote", depth)
        self.list_stack: list = []

    # ---- 공개 진입점 ---- #

    def render(self, markdown_text: str) -> None:
        md = MarkdownIt("commonmark").enable("table")
        tokens = md.parse(markdown_text)
        self._render_tokens(tokens)

    # ---- 런 스타일 결정 ---- #

    def _run_style_id(self, *, bold: bool, italic: bool) -> str:
        if bold and italic:
            return self.cp_bold_italic
        if bold:
            return self.cp_bold
        if italic:
            return self.cp_italic
        return self.cp_regular

    # ---- 단락 / 인라인 ---- #

    def _new_paragraph(self, *, style_id: str | None = None):
        kwargs = {"include_run": False}
        if style_id is not None:
            kwargs["style_id_ref"] = style_id
        return self.doc.add_paragraph("", **kwargs)

    def _emit_inline_runs(self, para, children: Iterable) -> None:
        """markdown-it inline 토큰의 children 을 순회하며 run 을 추가."""
        bold = False
        italic = False
        for tok in children:
            t = tok.type
            if t == "strong_open":
                bold = True
            elif t == "strong_close":
                bold = False
            elif t == "em_open":
                italic = True
            elif t == "em_close":
                italic = False
            elif t == "text":
                if tok.content:
                    para.add_run(
                        tok.content,
                        char_pr_id_ref=self._run_style_id(bold=bold, italic=italic),
                    )
            elif t == "code_inline":
                # T2: 백틱 + 굵게로 시각적 구분 (T3 에서 monospace + 음영)
                para.add_run(
                    f"`{tok.content}`",
                    char_pr_id_ref=self.cp_bold,
                )
            elif t == "softbreak":
                # 소프트 줄바꿈 → 단락 내부에서는 공백으로 취급
                para.add_run(" ", char_pr_id_ref=self.cp_regular)
            elif t == "hardbreak":
                # 하드 줄바꿈 — 본래 새 단락이 맞지만 인라인 컨텍스트에서
                # 단순화를 위해 공백으로 대체
                para.add_run("  ", char_pr_id_ref=self.cp_regular)
            elif t == "link_open":
                # T3 에서 하이퍼링크. T2 에서는 밑줄 런으로만 표시.
                bold_before, italic_before = bold, italic
                # 밑줄 on 상태로 표시하기 위해 별도 id 를 쓰지만 본 구현에서는
                # text 토큰이 올 때 계속 기본 스타일만 참조한다. 간단화를 위해
                # 일단 flag 변화만 예약.
                tok._saved = (bold_before, italic_before)
            elif t == "link_close":
                pass
            # 그 외(softbreak, image, s_open 등) — T3 에서 처리
            else:
                if hasattr(tok, "content") and tok.content:
                    para.add_run(
                        tok.content,
                        char_pr_id_ref=self._run_style_id(bold=bold, italic=italic),
                    )

    def _current_list_prefix(self) -> str:
        """현재 리스트 스택 상태에서 사용할 들여쓰기 + 마커 문자열."""
        if not self.list_stack:
            return ""
        frame = self.list_stack[-1]
        kind = frame[0]
        depth = frame[1]
        indent = LIST_INDENT * depth
        if kind == "ordered":
            num = frame[2]
            return f"{indent}{num}. "
        if kind == "blockquote":
            return f"{indent}│ "  # 세로 파이프로 인용 표시
        return f"{indent}{_bullet_for_depth(depth)} "

    def _bump_list_counter(self) -> None:
        if self.list_stack and self.list_stack[-1][0] == "ordered":
            kind, depth, num = self.list_stack[-1]
            self.list_stack[-1] = (kind, depth, num + 1)

    # ---- 표 ---- #

    def _render_table(self, tokens: list, start: int) -> int:
        """table_open 에서 시작해 table_close 까지 소비. 끝 인덱스+1 반환."""
        # 토큰 스캔으로 행/열 수 산출
        rows: list[list[str]] = []
        current_row: list[str] = []
        cell_text_buf: list[str] = []
        in_cell = False
        i = start + 1
        depth_table = 1
        while i < len(tokens) and depth_table > 0:
            tok = tokens[i]
            t = tok.type
            if t == "table_open":
                depth_table += 1
            elif t == "table_close":
                depth_table -= 1
                if depth_table == 0:
                    break
            elif t in ("thead_open", "thead_close", "tbody_open", "tbody_close"):
                pass
            elif t == "tr_open":
                current_row = []
            elif t == "tr_close":
                rows.append(current_row)
            elif t in ("th_open", "td_open"):
                in_cell = True
                cell_text_buf = []
            elif t in ("th_close", "td_close"):
                in_cell = False
                current_row.append("".join(cell_text_buf))
            elif t == "inline" and in_cell:
                # 셀 내부 인라인 — T2 에서는 평문으로
                cell_text_buf.append(tok.content)
            i += 1

        if not rows:
            return i + 1

        n_rows = len(rows)
        n_cols = max(len(r) for r in rows)
        table = self.doc.add_table(rows=n_rows, cols=n_cols)
        for ri, row in enumerate(rows):
            for ci in range(n_cols):
                txt = row[ci] if ci < len(row) else ""
                try:
                    table.rows[ri].cells[ci].text = txt
                except Exception:
                    # 셀 구조가 특이하면 조용히 스킵
                    pass
        return i + 1  # skip table_close

    # ---- 메인 루프 ---- #

    def _render_tokens(self, tokens: list) -> None:
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            t = tok.type

            if t == "heading_open":
                level = int(tok.tag[1:])  # 'h1' → 1
                inline = tokens[i + 1]
                style = self.heading_styles.get(level) or self.body_style
                para = self._new_paragraph(style_id=style)
                self._emit_inline_runs(para, inline.children or [])
                i += 3
                continue

            if t == "paragraph_open":
                inline = tokens[i + 1]
                para = self._new_paragraph(style_id=self.body_style)
                prefix = self._current_list_prefix()
                if prefix:
                    para.add_run(prefix, char_pr_id_ref=self.cp_regular)
                self._emit_inline_runs(para, inline.children or [])
                i += 3
                continue

            if t == "bullet_list_open":
                depth = sum(1 for _ in self.list_stack)
                self.list_stack.append(("bullet", depth))
                i += 1
                continue

            if t == "ordered_list_open":
                depth = sum(1 for _ in self.list_stack)
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
                i += 1
                continue

            if t == "list_item_close":
                self._bump_list_counter()
                i += 1
                continue

            if t == "fence" or t == "code_block":
                lang = (tok.info or "").strip()
                para = self._new_paragraph(style_id=self.body_style)
                para.add_run(f"```{lang}" if lang else "```", char_pr_id_ref=self.cp_bold)
                for line in tok.content.splitlines() or [""]:
                    p = self._new_paragraph(style_id=self.body_style)
                    p.add_run(line, char_pr_id_ref=self.cp_regular)
                para_end = self._new_paragraph(style_id=self.body_style)
                para_end.add_run("```", char_pr_id_ref=self.cp_bold)
                i += 1
                continue

            if t == "hr":
                para = self._new_paragraph(style_id=self.body_style)
                para.add_run("─" * 40, char_pr_id_ref=self.cp_regular)
                i += 1
                continue

            if t == "blockquote_open":
                depth = sum(1 for _ in self.list_stack)
                self.list_stack.append(("blockquote", depth))
                i += 1
                continue

            if t == "blockquote_close":
                if self.list_stack and self.list_stack[-1][0] == "blockquote":
                    self.list_stack.pop()
                i += 1
                continue

            if t == "table_open":
                i = self._render_table(tokens, i)
                continue

            # 기타 블록 — 평문 덤프
            if hasattr(tok, "content") and tok.content:
                for line in tok.content.splitlines():
                    p = self._new_paragraph(style_id=self.body_style)
                    p.add_run(line, char_pr_id_ref=self.cp_regular)
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
