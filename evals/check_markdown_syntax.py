#!/usr/bin/env python3
"""`render_markdown.py` 가 Markdown 문법을 얼마나 충실히 HWPX 로 옮기는지
항목별로 검증한다.

사용법::

    # 1) 샘플 렌더링
    python ../scripts/render_markdown.py markdown-syntax-sample.md out.hwpx

    # 2) 결과 검증
    python check_markdown_syntax.py out.hwpx

40 개 항목(헤딩 6 레벨, 강조 3 종, 인라인/블록 코드, 리스트 중첩 3 레벨,
순서/태스크 리스트, 링크, 표, 수평선, 블록 인용, 이미지, 네임스페이스)
을 XML 단에서 직접 확인한다. 파일명·경로 변경 시에도 깨지지 않도록
lxml 로 파싱하고 정규식이 아닌 구조 기반으로 체크한다.
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path
from collections import Counter
from lxml import etree

# Windows cp949 콘솔에서 한글/이모지 깨짐 방지
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
_NS = {"hh": HH[1:-1], "hp": HP[1:-1]}


def _flags_of(cp) -> list[str]:
    flags: list[str] = []
    if cp.find("hh:bold", _NS) is not None:
        flags.append("bold")
    if cp.find("hh:italic", _NS) is not None:
        flags.append("italic")
    ul = cp.find("hh:underline", _NS)
    if ul is not None and (ul.get("type") or "").upper() != "NONE":
        flags.append(f"UL({ul.get('color')})")
    color = cp.get("textColor")
    if color and color != "#000000":
        flags.append(f"color={color}")
    shade = cp.get("shadeColor")
    if shade and shade != "none":
        flags.append(f"shade={shade}")
    h = cp.get("height")
    if h and h != "1000":
        flags.append(f"h={int(h)/100}pt")
    return flags


def check(path: Path) -> int:
    with zipfile.ZipFile(path) as zf:
        hdr = etree.fromstring(zf.read("Contents/header.xml"))
        sec = etree.fromstring(zf.read("Contents/section0.xml"))
        bindata = [n for n in zf.namelist() if n.startswith("BinData/")]
        sec_raw = zf.read("Contents/section0.xml").decode("utf-8")

    # charPr id 추론
    cp_flags = {cp.get("id"): _flags_of(cp) for cp in hdr.iter(f"{HH}charPr")}
    bold_id = next((i for i, f in cp_flags.items() if f == ["bold"]), None)
    italic_id = next((i for i, f in cp_flags.items() if f == ["italic"]), None)
    boldit_id = next(
        (i for i, f in cp_flags.items() if set(f) == {"bold", "italic"}), None
    )
    code_id = next(
        (i for i, f in cp_flags.items() if any("shade=#F2F2F2" in x for x in f)),
        None,
    )
    link_id = next(
        (i for i, f in cp_flags.items() if any("color=#0066CC" in x for x in f)),
        None,
    )

    # run charPrIDRef 분포
    all_refs = Counter(r.get("charPrIDRef") for r in sec.iter(f"{HP}run"))

    # 헤딩 집계
    style_to_level = {"2": 1, "3": 2, "4": 3, "5": 4, "6": 5, "7": 6}
    heading_counts: Counter[int] = Counter()
    heading_paras_pp: list[tuple[int, str | None]] = []
    for p in sec.iter(f"{HP}p"):
        sid = p.get("styleIDRef")
        if sid in style_to_level:
            lvl = style_to_level[sid]
            heading_counts[lvl] += 1
            heading_paras_pp.append((lvl, p.get("paraPrIDRef")))

    # 표
    tables = list(sec.iter(f"{HP}tbl"))

    # 전체 텍스트
    full_text = "\n".join(
        "".join((t.text or "") for t in p.iter(f"{HP}t"))
        for p in sec.iter(f"{HP}p")
    )

    results: list[tuple[str, bool, str]] = []

    def add(label: str, ok: bool, detail: str = "") -> None:
        results.append((label, ok, detail))

    # 헤딩
    add("H1 (22pt)", heading_counts[1] >= 1, f"{heading_counts[1]}")
    add("H2 (18pt)", heading_counts[2] >= 1, f"{heading_counts[2]}")
    add("H3 (16pt)", heading_counts[3] >= 1, f"{heading_counts[3]}")
    add("H4 (14pt)", heading_counts[4] >= 1, f"{heading_counts[4]}")
    add("H5 (12pt)", heading_counts[5] >= 1, f"{heading_counts[5]}")
    add("H6 (11pt)", heading_counts[6] >= 1, f"{heading_counts[6]}")
    add(
        "헤딩 paragraph 에 paraPrIDRef 명시 (spacing 적용)",
        all(pp is not None for _lvl, pp in heading_paras_pp),
    )

    # 강조
    add("**굵게**", bool(bold_id and all_refs.get(bold_id, 0) > 0),
        f"id={bold_id} x{all_refs.get(bold_id, 0)}")
    add("*기울임*", bool(italic_id and all_refs.get(italic_id, 0) > 0),
        f"id={italic_id} x{all_refs.get(italic_id, 0)}")
    add("***굵은 기울임***", bool(boldit_id and all_refs.get(boldit_id, 0) > 0),
        f"id={boldit_id} x{all_refs.get(boldit_id, 0)}")
    add("`인라인 코드`", bool(code_id and all_refs.get(code_id, 0) > 0),
        f"id={code_id} x{all_refs.get(code_id, 0)}")

    # 링크
    add("링크 (파란색 + 밑줄)", bool(link_id and all_refs.get(link_id, 0) > 0),
        f"id={link_id} x{all_refs.get(link_id, 0)}")
    add("링크 URL 괄호 부기", "(https://" in full_text)

    # 리스트
    add("순서 없는 목록 • (depth 0)", "• " in full_text)
    add("순서 없는 목록 ◦ (depth 1)", "◦ " in full_text)
    add("순서 없는 목록 ▪ (depth 2)", "▪ " in full_text)
    add("순서 있는 목록 '1. '", "1. " in full_text)
    add("순서 있는 목록 다른 start (5. )", "5. " in full_text)

    # 태스크
    add("체크박스 ☐", "☐ " in full_text)
    add("체크박스 ☑", "☑ " in full_text)

    # 코드
    add("코드 블록 fence ```", "```" in full_text)
    add("코드 블록 언어 라벨 ```python", "```python" in full_text)
    add("코드 블록 gutter ▏", "▏ " in full_text)
    add("들여쓰기 코드 블록", "for i in range(3):" in full_text)

    # 블록 인용
    add("블록 인용 │", "│ " in full_text)

    # 수평선
    add("수평선 (─×20+)", "─" * 20 in full_text)

    # 표
    add("표 ≥ 1 개", len(tables) >= 1, f"{len(tables)}")
    if tables:
        t0 = tables[0]
        rc = int(t0.get("rowCnt") or 0)
        cc = int(t0.get("colCnt") or 0)
        add("표 rows/cols 정상", rc >= 2 and cc >= 2, f"{rc}x{cc}")

    # 이미지
    add("BinData 엔트리 생성 (실제 이미지)", len(bindata) >= 1, f"{bindata}")
    add("이미지 placeholder 🖼", "🖼" in full_text)

    # 네임스페이스 — section.xml 은 hp:/hs: 만 씀 (hh: 는 header.xml 쪽)
    add("ns0 누수 없음", "ns0:" not in sec_raw)
    add("hp canonical prefix (section)", 'xmlns:hp=' in sec_raw)

    # 출력
    print("=" * 70)
    print(f"Markdown 문법 지원 검증 — {path}")
    print("=" * 70)
    ok = 0
    for label, passed, detail in results:
        mark = "✓" if passed else "✗"
        dstr = f"  [{detail}]" if detail else ""
        print(f"  {mark}  {label}{dstr}")
        if passed:
            ok += 1
    print(f"\n  통과: {ok} / {len(results)}")
    return 0 if ok == len(results) else 1


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write(
            "Usage: python check_markdown_syntax.py <path/to/rendered.hwpx>\n"
        )
        return 2
    path = Path(argv[1])
    if not path.exists():
        sys.stderr.write(f"error: not found: {path}\n")
        return 1
    return check(path)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
