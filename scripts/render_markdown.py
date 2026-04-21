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
# T3 — 폰트 / 링크 / 코드 스타일                                             #
# --------------------------------------------------------------------------- #


def _add_font(doc: HwpxDocument, face: str, lang: str) -> int | None:
    """주어진 언어의 fontface 에 글꼴을 추가하고 id 반환. 이미 있으면 그 id."""
    header = doc.headers[0]
    for ff in header.element.iter(f"{_HH}fontface"):
        if ff.get("lang") != lang:
            continue
        for f in ff.findall(f"{_HH}font"):
            if f.get("face") == face:
                return int(f.get("id"))
        existing_ids = [int(f.get("id")) for f in ff.findall(f"{_HH}font")]
        new_id = max(existing_ids, default=-1) + 1
        new_font = _LXML_ET.SubElement(ff, f"{_HH}font")
        new_font.set("id", str(new_id))
        new_font.set("face", face)
        new_font.set("type", "TTF")
        new_font.set("isEmbedded", "0")
        ff.set("fontCnt", str(len(ff.findall(f"{_HH}font"))))
        header.mark_dirty()
        return new_id
    return None


def _ensure_link_charpr(doc: HwpxDocument) -> str:
    """파란색 + 밑줄 인 링크용 charPr id 반환."""
    header = doc.headers[0]
    link_color = "#0066CC"

    def predicate(el) -> bool:
        if el.get("textColor") != link_color:
            return False
        ul = el.find(f"{_HH}underline")
        return ul is not None and (ul.get("type") or "").upper() == "SOLID"

    def modifier(el) -> None:
        el.set("textColor", link_color)
        for ul in list(el.findall(f"{_HH}underline")):
            el.remove(ul)
        _LXML_ET.SubElement(
            el,
            f"{_HH}underline",
            {"type": "SOLID", "shape": "SOLID", "color": link_color},
        )

    new_el = header.ensure_char_property(
        predicate=predicate,
        modifier=modifier,
        base_char_pr_id="0",
    )
    return new_el.get("id")


def _ensure_code_charpr(doc: HwpxDocument, *, mono_font_id_latin: int | None) -> str:
    """모노스페이스 + 연한 음영인 코드용 charPr id 반환."""
    header = doc.headers[0]
    shade = "#F2F2F2"

    def predicate(el) -> bool:
        if el.get("shadeColor") != shade:
            return False
        fr = el.find(f"{_HH}fontRef")
        if fr is None or mono_font_id_latin is None:
            return mono_font_id_latin is None
        return fr.get("latin") == str(mono_font_id_latin)

    def modifier(el) -> None:
        el.set("shadeColor", shade)
        if mono_font_id_latin is not None:
            fr = el.find(f"{_HH}fontRef")
            if fr is not None:
                fr.set("latin", str(mono_font_id_latin))

    new_el = header.ensure_char_property(
        predicate=predicate,
        modifier=modifier,
        base_char_pr_id="0",
    )
    return new_el.get("id")


# 제목 레벨별 글자 크기(1/100 pt). 워드 기본 헤딩 사이즈와 유사.
HEADING_HEIGHTS = {
    1: 2200,  # 22pt
    2: 1800,  # 18pt
    3: 1600,  # 16pt
    4: 1400,  # 14pt
    5: 1200,  # 12pt
    6: 1100,  # 11pt
}

# 제목 레벨별 paragraph 위/아래 여백 (before/after, 1/100 pt).
# 본문과의 시각적 구분을 위해 before 를 크게 잡는다.
HEADING_SPACING = {
    1: (2400, 600),   # 24pt / 6pt
    2: (1800, 400),   # 18pt / 4pt
    3: (1400, 400),   # 14pt / 4pt
    4: (1200, 400),   # 12pt / 4pt
    5: (1000, 400),
    6: (1000, 400),
}


_HP_NS = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def _ensure_heading_paragraph_spacing(doc: HwpxDocument) -> None:
    """개요 1~6 스타일이 참조하는 paraPr 에 before/after 여백을 주입한다.

    기본 템플릿의 개요 1~6 paraPr 에는 `<hp:spacing>` 가 없어 헤딩 앞뒤에
    공간이 생기지 않는다. 각 스타일이 가리키는 paraPr 를 찾아 spacing 자식
    요소를 추가/갱신한다.
    """
    header = doc.headers[0]
    # 스타일 name → paraPrIDRef 매핑
    style_to_pp: dict[str, str] = {}
    for s in header.element.iter(f"{_HH}style"):
        name = s.get("name") or ""
        if name in HEADING_STYLE_NAMES.values():
            style_to_pp[name] = s.get("paraPrIDRef")

    modified = False
    for lvl, name in HEADING_STYLE_NAMES.items():
        pp_id = style_to_pp.get(name)
        if pp_id is None:
            continue
        before, after = HEADING_SPACING.get(lvl, (1000, 400))
        for pp in header.element.iter(f"{_HH}paraPr"):
            if pp.get("id") != pp_id:
                continue
            spacing = pp.find(f"{_HP_NS}spacing")
            if spacing is None:
                spacing = _LXML_ET.SubElement(pp, f"{_HP_NS}spacing")
            spacing.set("before", str(before))
            spacing.set("after", str(after))
            modified = True
            break

    if modified:
        header.mark_dirty()


def _style_para_pr_id(doc: HwpxDocument, style_id: str | None) -> str | None:
    """스타일 id 의 paraPrIDRef 반환. 없으면 None."""
    if style_id is None:
        return None
    header = doc.headers[0]
    for s in header.element.iter(f"{_HH}style"):
        if s.get("id") == str(style_id):
            pp = s.get("paraPrIDRef")
            return pp if pp else None
    return None


def _ensure_heading_charpr(doc: HwpxDocument, level: int) -> str:
    """레벨별 헤딩 run 용 charPr (큰 글자 + 굵게) id 반환.

    HwpxDocument.new() 기본 템플릿의 "개요 1~10" 스타일은 paraPrIDRef
    만 다르고 charPrIDRef 가 모두 "0"(=본문 10pt 바탕글) 이다. 따라서
    스타일만 적용하면 제목이 본문과 동일한 글자 크기로 렌더된다. 이
    헬퍼는 레벨별로 큰 글자 + bold 인 전용 charPr 을 생성해 런 레벨에서
    직접 참조하게 한다.
    """
    height = str(HEADING_HEIGHTS.get(level, 1100))
    header = doc.headers[0]

    def predicate(el) -> bool:
        if el.get("height") != height:
            return False
        return el.find(f"{_HH}bold") is not None and el.find(f"{_HH}italic") is None

    def modifier(el) -> None:
        el.set("height", height)
        for b in list(el.findall(f"{_HH}bold")):
            el.remove(b)
        _LXML_ET.SubElement(el, f"{_HH}bold")
        for it in list(el.findall(f"{_HH}italic")):
            el.remove(it)

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
        # T3 — 링크 / 코드
        self.cp_link = _ensure_link_charpr(doc)
        mono_latin = _add_font(doc, "Consolas", "LATIN")
        self.cp_code = _ensure_code_charpr(doc, mono_font_id_latin=mono_latin)
        # T4 — 헤딩 전용 charPr (레벨별 큰 글자 + 굵게)
        self.heading_cp = {
            lvl: _ensure_heading_charpr(doc, lvl) for lvl in range(1, 7)
        }
        # T4+ — 개요 1~6 paraPr 에 위/아래 여백 주입 (기본 템플릿에는 없음)
        _ensure_heading_paragraph_spacing(doc)
        # 각 헤딩 레벨의 paraPrIDRef (paragraph 에 명시적으로 붙여 spacing 적용)
        self.heading_pp = {
            lvl: _style_para_pr_id(doc, self.heading_styles.get(lvl))
            for lvl in range(1, 7)
        }
        # 리스트 상태: 스택 기반 중첩 추적
        # 각 항목: ("bullet", depth) / ("ordered", depth, next_number) / ("blockquote", depth)
        self.list_stack: list = []
        # 이미지 처리 추적 (참고용)
        self.images_embedded: list[dict] = []

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

    def _new_paragraph(
        self, *, style_id: str | None = None, para_pr_id: str | None = None
    ):
        kwargs = {"include_run": False}
        if style_id is not None:
            kwargs["style_id_ref"] = style_id
        if para_pr_id is not None:
            kwargs["para_pr_id_ref"] = para_pr_id
        return self.doc.add_paragraph("", **kwargs)

    def _emit_inline_flat(self, para, children: Iterable, cp_id: str) -> None:
        """헤딩/캡션처럼 단일 스타일을 유지해야 하는 단락용.

        markdown 인라인 중 text / code_inline / softbreak / hardbreak 의
        텍스트만 추출해 모두 ``cp_id`` 로 출력한다. strong/em/link 마커는
        본문 텍스트만 남기고 형식은 무시한다.
        """
        for tok in children:
            t = tok.type
            if t == "text":
                if tok.content:
                    para.add_run(tok.content, char_pr_id_ref=cp_id)
            elif t == "code_inline":
                para.add_run(f"`{tok.content}`", char_pr_id_ref=cp_id)
            elif t in ("softbreak", "hardbreak"):
                para.add_run(" ", char_pr_id_ref=cp_id)
            # strong_open/close, em_open/close, link_open/close, image → 평탄화로 스킵

    def _emit_inline_runs(self, para, children: Iterable) -> None:
        """markdown-it inline 토큰의 children 을 순회하며 run 을 추가."""
        bold = False
        italic = False
        in_link = False
        link_href: str | None = None
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
            elif t == "link_open":
                in_link = True
                link_href = tok.attrGet("href")
            elif t == "link_close":
                # URL 도 괄호로 덧붙여 인쇄 매체에서도 찾아갈 수 있게 한다.
                if link_href:
                    para.add_run(
                        f" ({link_href})",
                        char_pr_id_ref=self.cp_regular,
                    )
                in_link = False
                link_href = None
            elif t == "text":
                if tok.content:
                    if in_link:
                        # 링크 본문은 파란색 + 밑줄
                        para.add_run(tok.content, char_pr_id_ref=self.cp_link)
                    else:
                        para.add_run(
                            tok.content,
                            char_pr_id_ref=self._run_style_id(
                                bold=bold, italic=italic
                            ),
                        )
            elif t == "code_inline":
                # T3: 백틱 래핑 + 모노스페이스 + 음영
                para.add_run(
                    f"`{tok.content}`",
                    char_pr_id_ref=self.cp_code,
                )
            elif t == "softbreak":
                para.add_run(" ", char_pr_id_ref=self.cp_regular)
            elif t == "hardbreak":
                para.add_run("  ", char_pr_id_ref=self.cp_regular)
            elif t == "image":
                # T3: 이미지는 BinData 에 등록하고 본문에는 플레이스홀더로
                src = tok.attrGet("src") or ""
                alt = tok.content or tok.attrGet("alt") or ""
                info = self._try_embed_image(src, alt)
                placeholder = info["placeholder"] if info else f"[🖼 {alt} ({src})]"
                para.add_run(placeholder, char_pr_id_ref=self.cp_italic)
            elif t == "s_open" or t == "s_close":
                # 취소선은 T3 에서도 미지원 (XML 저수준 필요). 통과.
                pass
            else:
                if hasattr(tok, "content") and tok.content:
                    para.add_run(
                        tok.content,
                        char_pr_id_ref=self._run_style_id(
                            bold=bold, italic=italic
                        ),
                    )

    def _try_embed_image(self, src: str, alt: str) -> dict | None:
        """이미지 파일이 로컬에 있으면 BinData 에 등록. 성공 시 플레이스홀더
        텍스트를 포함한 dict 반환. 실패하면 None."""
        if not src:
            return None
        src_path = Path(src)
        if not src_path.is_absolute():
            src_path = Path.cwd() / src
        if not src_path.exists() or not src_path.is_file():
            return None
        ext = src_path.suffix.lstrip(".").lower()
        if ext not in {"png", "jpg", "jpeg", "gif", "bmp", "tiff", "tif", "svg"}:
            return None
        try:
            data = src_path.read_bytes()
            item_id = self.doc.add_image(data, ext)
        except Exception:
            return None
        info = {
            "src": str(src_path),
            "item_id": item_id,
            "alt": alt,
            "placeholder": f"[🖼 {alt or src_path.name} • BinData/{item_id}.{ext}]",
        }
        self.images_embedded.append(info)
        return info

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
                cp = self.heading_cp.get(level) or self.cp_regular
                pp = self.heading_pp.get(level)
                para = self._new_paragraph(style_id=style, para_pr_id=pp)
                # 헤딩 내 인라인 서식(굵게·기울임·링크·코드) 은 평탄화한다.
                # 헤딩 텍스트 전체가 큰 글자 + 굵게이기 때문에 강조가 의미가 없고,
                # 추가 charPr 파생을 억제해 파일 크기도 줄인다.
                self._emit_inline_flat(para, inline.children or [], cp)
                i += 3
                continue

            if t == "paragraph_open":
                inline = tokens[i + 1]
                para = self._new_paragraph(style_id=self.body_style)
                prefix = self._current_list_prefix()
                # T3: 리스트 아이템의 첫 텍스트가 GFM 태스크 마커면 ☐/☑ 로 치환
                children = list(inline.children or [])
                if prefix and children and children[0].type == "text":
                    first = children[0]
                    content = first.content or ""
                    if content.startswith("[ ] "):
                        prefix = prefix + "☐ "
                        children[0].content = content[4:]
                    elif content.lower().startswith("[x] "):
                        prefix = prefix + "☑ "
                        children[0].content = content[4:]
                if prefix:
                    para.add_run(prefix, char_pr_id_ref=self.cp_regular)
                self._emit_inline_runs(para, children)
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
                para.add_run(
                    f"```{lang}" if lang else "```",
                    char_pr_id_ref=self.cp_bold,
                )
                for line in tok.content.splitlines() or [""]:
                    p = self._new_paragraph(style_id=self.body_style)
                    # T3: 모노스페이스 + 음영 (뷰어/폰트 환경에 따라 안 보일 수 있음)
                    # T4+: 좌측 gutter ▏ 를 덧붙여 shadeColor / Consolas 폰트가
                    #      렌더 안 되는 뷰어에서도 코드 라인임을 항상 구분 가능.
                    p.add_run(f"▏ {line}", char_pr_id_ref=self.cp_code)
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
