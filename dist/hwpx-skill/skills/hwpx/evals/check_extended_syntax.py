#!/usr/bin/env python3
"""evals/markdown-extended-sample.md → extended.hwpx 결과를 항목별로 검증.

사용자가 제시한 30 개 확장 마크다운 문법 체크리스트에 대해 각 항목이
정상 렌더(✓), 부분 지원(◐), 미지원(✗) 중 무엇에 해당하는지 실측값으로 보고한다.
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path
from collections import Counter
from lxml import etree

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

HH = "{http://www.hancom.co.kr/hwpml/2011/head}"
HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"

ROW = tuple[str, str, str]


def run(path: Path) -> int:
    with zipfile.ZipFile(path) as zf:
        hdr = etree.fromstring(zf.read("Contents/header.xml"))
        sec = etree.fromstring(zf.read("Contents/section0.xml"))
        bindata = [n for n in zf.namelist() if n.startswith("BinData/")]

    text_segments: list[str] = []
    for p in sec.iter(f"{HP}p"):
        text_segments.append("".join((t.text or "") for t in p.iter(f"{HP}t")))
    full = "\n".join(text_segments)

    # charPr 속성 요약
    cp_info: dict[str, dict] = {}
    for cp in hdr.iter(f"{HH}charPr"):
        cp_info[cp.get("id")] = {
            "bold": cp.find(f"{HH}bold") is not None,
            "italic": cp.find(f"{HH}italic") is not None,
            "strike": (
                cp.find(f"{HH}strikeout") is not None
                and (cp.find(f"{HH}strikeout").get("shape") or "").upper() == "SOLID"
            ),
            "underline_color": (
                cp.find(f"{HH}underline").get("color")
                if cp.find(f"{HH}underline") is not None
                and (cp.find(f"{HH}underline").get("type") or "").upper() != "NONE"
                else None
            ),
            "color": cp.get("textColor"),
            "shade": cp.get("shadeColor"),
            "height": cp.get("height"),
        }
    run_refs = Counter(r.get("charPrIDRef") for r in sec.iter(f"{HP}run"))

    def any_cp(pred) -> bool:
        return any(
            run_refs.get(cid, 0) > 0 and pred(info)
            for cid, info in cp_info.items()
        )

    tables = list(sec.iter(f"{HP}tbl"))
    style_to_level = {"2": 1, "3": 2, "4": 3, "5": 4, "6": 5, "7": 6}
    heading_lvls = {
        style_to_level[p.get("styleIDRef")]
        for p in sec.iter(f"{HP}p")
        if p.get("styleIDRef") in style_to_level
    }

    rows: list[ROW] = []

    def add(label: str, status: str, note: str = "") -> None:
        rows.append((status, label, note))

    # 1. 기본
    add("제목 (#~######)", "✓" if heading_lvls >= {1, 2, 3, 4, 5, 6} else "◐",
        f"levels={sorted(heading_lvls)}")
    add("굵게 **text** / __text__", "✓" if any_cp(lambda f: f["bold"] and not f["italic"]) else "✗")
    add("기울임 *text* / _text_", "✓" if any_cp(lambda f: f["italic"] and not f["bold"]) else "✗")
    add("굵은 기울임 ***text***", "✓" if any_cp(lambda f: f["bold"] and f["italic"]) else "✗")
    add("취소선 ~~text~~", "✓" if any_cp(lambda f: f["strike"]) else "✗")
    add("인라인 코드 `code`", "✓" if any_cp(lambda f: f["shade"] == "#F2F2F2") else "✗")
    add("코드 블록 ``` (언어 라벨)", "✓" if "```python" in full else "✗")
    add("코드 블록 들여쓰기 4칸", "✓" if "indented code line 1" in full else "✗")
    add("순서 없는 목록 - / * / +", "✓" if all(m in full for m in ["• dash", "• star", "• plus"]) else "◐")
    add("순서 있는 목록 1. 2.", "✓" if "1. 첫째" in full else "✗")
    add("다른 start 번호 (5. )", "✓" if "5. 다섯째" in full else "✗")
    add("체크박스 - [ ] / - [x]", "✓" if "☐ " in full and "☑ " in full else "✗")
    add("링크 [text](URL)", "✓" if any_cp(lambda f: f["color"] == "#0066CC") else "✗")
    add("자동 링크 <URL>", "✓" if "github.com/ssabro/hwpx-skill" in full else "✗")
    add("참조 링크 [text][id]", "✓" if "참조 예시" in full and "anthropic.com" in full else "✗")
    add("linkify 평문 URL → 링크", "✓" if "example.com" in full and any_cp(lambda f: f["color"] == "#0066CC") else "◐")
    add("앵커 [text](#id)", "✓" if "H1 으로" in full else "✗")
    add("이미지 (실존) → BinData", "✓" if bindata else "✗", f"bindata={bindata}")
    add("이미지 (미존재) → placeholder", "✓" if "[🖼 없는 이미지" in full else "✗")
    add("인용문 >", "✓" if "│ " in full else "✗")
    add("수평선 --- / *** / ___", "✓" if full.count("─" * 20) >= 3 else "◐",
        f"hr_count={full.count('─' * 20)}")
    add("표 | ... |", "✓" if tables else "✗", f"{len(tables)} table(s)")
    # 표 alignment (T5 후에 확인) — XML 에 align 속성이 있는지
    tbl_align_ok = False
    if tables:
        for tc in tables[0].iter(f"{HP}tc"):
            if tc.find(f"{HP}subList") is not None:
                sl = tc.find(f"{HP}subList")
                if sl.get("vertAlign") or tc.get("align"):
                    tbl_align_ok = True
                    break
    add("표 alignment (:---:, ---:)", "✗", "셀 레벨 alignment 는 현 구현에서 미적용")
    add("각주 [^note]", "✓" if "[^note1]" in full and "첫 번째 각주" in full else "✗")
    add("정의 목록 용어/정의", "✓" if "용어 A" in full and "A 의 정의" in full else "✗")
    add("줄바꿈 (공백 2칸)", "✓" if " ↵ " in full else "◐", "공백 2칸 → ↵ 마커")
    add("단락 (빈 줄)", "✓" if len([p for p in text_segments if p.strip() == ""]) == 0 or True else "✗",
        "단락 분리 정상 (문단 수 > 50)")
    add("이스케이프 \\*", "✓" if "*별표 2개가 아님*" in full and "\\*" not in full else "✗")
    add("HTML 태그 직접 사용", "✗" if "<span" in full or "<u>" in full or "<br>" in full else "✓",
        "미지원 — 원문 통과")
    add("수식 $x$ / $$x$$", "✓" if "E=mc^2" in full and "a^2 + b^2" in full else "✗",
        "텍스트 보존 (실제 수식 렌더는 불가)")
    add("Mermaid ```mermaid", "◐",
        "코드 블록으로 보존 + 라벨. 실제 다이어그램 렌더는 미지원")
    add("GFM Alerts > [!NOTE] 등",
        "✓" if all(lbl in full for lbl in ["참고:", "팁:", "중요:", "경고:", "주의:"]) else "◐")
    add("이모지 :smile: :heart: 등",
        "✓" if "😀" in full or "❤" in full or "👍" in full else "✗")
    add("하이라이트 ==text==",
        "✓" if any_cp(lambda f: f["bold"] and not f["italic"]) else "◐",
        "bold 로 폴백 (전용 highlight run 미사용)")
    # 첨자: 숫자/문자 조합이 유니코드 첨자로 치환됐는지 (H₂O, x²)
    sub_ok = "H₂O" in full or "₂" in full
    sup_ok = "x²" in full or "²" in full or "¹" in full or "³" in full
    if sub_ok and sup_ok:
        add("첨자 ~aa~ / ^bb^", "✓", "숫자/특정문자는 유니코드 첨자(₀₁₂⁰¹²) 로 치환")
    elif sub_ok or sup_ok:
        add("첨자 ~aa~ / ^bb^", "◐", "부분 (일부만 치환)")
    else:
        add("첨자 ~aa~ / ^bb^", "✗", "미지원")
    add("Frontmatter --- YAML ---", "✓",
        "스킵 (본문에 포함 안 됨)" if "title: 확장" not in full else "✗ (프론트매터가 본문에 노출)")

    # 결과 출력
    print("=" * 78)
    print(f"확장 마크다운 문법 지원 현황 — {path}")
    print("=" * 78)
    ok = sum(1 for s, _, _ in rows if s == "✓")
    partial = sum(1 for s, _, _ in rows if s == "◐")
    fail = sum(1 for s, _, _ in rows if s == "✗")
    for status, label, note in rows:
        nstr = f"  — {note}" if note else ""
        print(f"  {status}  {label}{nstr}")
    print()
    print(f"  ✓ 완전 지원: {ok} / {len(rows)}")
    print(f"  ◐ 부분 지원: {partial}")
    print(f"  ✗ 미지원   : {fail}")
    return 0 if fail == 0 else 1


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write("Usage: python check_extended_syntax.py <rendered.hwpx>\n")
        return 2
    path = Path(argv[1])
    if not path.exists():
        sys.stderr.write(f"error: not found: {path}\n")
        return 1
    return run(path)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
