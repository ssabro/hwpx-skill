#!/usr/bin/env python3
"""Markdown → HWPX 평문 덤프 유틸.

Markdown 문법을 렌더링하지 않고 원문 그대로 한 줄씩 단락으로 적재해
간이 샘플/미리보기용 .hwpx 를 만든다. 제목/굵게 등은 문자 그대로 보인다.

사용법::

    python dump_markdown.py INPUT.md [OUTPUT.hwpx]
    cat notes.md | python dump_markdown.py - notes.hwpx

OUTPUT 생략 시 CWD 에 ``<stem>.hwpx`` 저장. INPUT 이 ``-`` 이면 stdin,
기본 출력명은 ``stdin.hwpx``.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from hwpx.document import HwpxDocument
except ImportError:  # pragma: no cover
    sys.stderr.write("error: python-hwpx 가 설치되지 않았습니다.\n")
    raise SystemExit(1)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hwpx_toolkit import normalize_namespaces_in_place


def _read_source(token: str) -> tuple[str, str]:
    """(본문, 기본 출력 stem). ``-`` 는 stdin 처리."""
    if token == "-":
        return sys.stdin.read(), "stdin"
    src = Path(token)
    if not src.exists():
        raise FileNotFoundError(f"input not found: {src}")
    return src.read_text(encoding="utf-8"), src.stem


def _iter_paragraphs(text: str):
    """줄 단위 순회, 연속 빈 줄은 하나로 수축."""
    blank_pending = False
    for raw in text.splitlines():
        if raw.strip() == "":
            blank_pending = True
            continue
        if blank_pending:
            yield ""
            blank_pending = False
        yield raw


def dump(text: str, output: Path) -> tuple[Path, int]:
    """``text`` 를 단락으로 풀어 저장. (경로, 단락 수) 반환."""
    doc = HwpxDocument.new()
    lines = 0
    for para in _iter_paragraphs(text):
        doc.add_paragraph(para)
        lines += 1
    output.parent.mkdir(parents=True, exist_ok=True)
    doc.save_to_path(str(output))
    normalize_namespaces_in_place(str(output))
    return output, lines


def _run(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        sys.stderr.write("Usage: python dump_markdown.py INPUT.md [OUTPUT.hwpx]\n")
        return 2
    try:
        text, default_stem = _read_source(argv[1])
    except FileNotFoundError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    output = Path(argv[2]) if len(argv) == 3 else Path.cwd() / f"{default_stem}.hwpx"
    try:
        written, lines = dump(text, output)
    except Exception as exc:  # noqa: BLE001 — CLI surface
        sys.stderr.write(f"error: {exc}\n")
        return 1
    sys.stdout.write(f"ok: {written} ({lines} paragraphs, {written.stat().st_size} bytes)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run(sys.argv))
