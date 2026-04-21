#!/usr/bin/env python3
"""기본 보고서 스켈레톤(.hwpx) 빌더.

``assets/report-skeleton.hwpx`` 를 **프로그래밍 방식으로 새로** 생성한다.
바이너리 템플릿을 원격 저장소나 서드파티로부터 가져오지 않으며,
python-hwpx 가 기본 제공하는 API 만으로 플레이스홀더 문자열이 박힌
최소 구조의 문서를 만든다.

생성 결과는 다음과 같은 마커를 포함한다 (마커 명명 규칙은 이 프로젝트
고유이다):

================ ======================== ============================
마커              역할                       치환 방식
================ ======================== ============================
{{ORG_NAME}}      발행 기관명               replace_all
{{REPORT_TITLE}}  보고서 제목               replace_all
{{REPORT_DATE}}   작성일                    replace_all
{{DOC_SUBTITLE}}  본문 상단 타이틀          replace_all
{{HEADING_L1}}    1단계(□) 제목             replace_ordered
{{HEADING_L2}}    2단계(○) 소제목           replace_ordered
{{BODY_L3}}       3단계(―) 본문             replace_ordered
{{NOTE_L4}}       4단계(※) 참고/주석        replace_ordered
================ ======================== ============================

실행::

    python build_report_skeleton.py
    python build_report_skeleton.py custom/output.hwpx
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import NamedTuple

try:
    from hwpx.document import HwpxDocument
except ImportError:  # pragma: no cover
    sys.stderr.write(
        "error: python-hwpx 가 설치되지 않았습니다.\n"
        "       pip install python-hwpx 후 다시 실행하세요.\n"
    )
    raise SystemExit(1)

from hwpx_toolkit import normalize_namespaces_in_place


# -- 스켈레톤 구성 --------------------------------------------------------

class BodySlot(NamedTuple):
    marker: str
    visual_prefix: str  # 에디터에서 육안으로 구분되도록 앞에 붙이는 기호/공백
    count: int           # 기본 생성 수량


COVER_MARKERS: tuple[str, ...] = (
    "{{ORG_NAME}}",
    "{{REPORT_TITLE}}",
    "{{REPORT_DATE}}",
)

SUBTITLE_MARKER = "{{DOC_SUBTITLE}}"

BODY_SLOTS: tuple[BodySlot, ...] = (
    BodySlot("{{HEADING_L1}}", "□ ",       5),
    BodySlot("{{HEADING_L2}}", "  ○ ",     6),
    BodySlot("{{BODY_L3}}",    "   ― ",    8),
    BodySlot("{{NOTE_L4}}",    "     ※ ", 6),
)

DEFAULT_OUTPUT = (
    Path(__file__).resolve().parent.parent / "assets" / "report-skeleton.hwpx"
)


# -- 구성 로직 ------------------------------------------------------------

def _render_cover(doc: "HwpxDocument") -> None:
    """표지 영역: 기관명 / 제목 / 작성일."""
    doc.add_paragraph("")
    for marker in COVER_MARKERS:
        doc.add_paragraph(marker)
        doc.add_paragraph("")


def _render_body(doc: "HwpxDocument") -> None:
    """본문 영역: 서브타이틀 후 계층별 마커 반복."""
    doc.add_paragraph(SUBTITLE_MARKER)
    doc.add_paragraph("")
    for slot in BODY_SLOTS:
        for _ in range(slot.count):
            doc.add_paragraph(f"{slot.visual_prefix}{slot.marker}")
        doc.add_paragraph("")


def build(output_path: Path) -> Path:
    """스켈레톤을 새로 생성해서 ``output_path`` 로 저장한다."""
    doc = HwpxDocument.new()
    _render_cover(doc)
    _render_body(doc)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save_to_path(str(output_path))
    normalize_namespaces_in_place(output_path)
    return output_path


# -- CLI -----------------------------------------------------------------

def _run(argv: list[str]) -> int:
    if len(argv) > 2:
        sys.stderr.write(
            "Usage: python build_report_skeleton.py [OUTPUT.hwpx]\n"
        )
        return 2

    target = Path(argv[1]) if len(argv) == 2 else DEFAULT_OUTPUT
    try:
        written = build(target)
    except Exception as exc:  # noqa: BLE001 — CLI surface
        sys.stderr.write(f"error: {exc}\n")
        return 1

    sys.stdout.write(f"ok: {written}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run(sys.argv))
