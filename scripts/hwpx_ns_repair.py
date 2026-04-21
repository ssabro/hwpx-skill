#!/usr/bin/env python3
"""CLI: HWPX 파일의 XML 네임스페이스 프리픽스를 정규화한다.

python-hwpx/ElementTree가 저장한 HWPX는 ``ns0``/``ns1`` 같은 자동
생성 prefix를 남기는 경우가 있어, 일부 Hangul Viewer(특히 macOS
빌드)에서 빈 페이지로 열리는 증상이 생긴다. 이 스크립트는 해당
prefix를 한컴 표준(hh/hc/hp/hs)으로 다시 매핑한다.

사용법::

    python hwpx_ns_repair.py path/to/file.hwpx

프로그램에서 호출할 때는 툴킷의 편의 함수를 직접 쓴다::

    from hwpx_toolkit import normalize_namespaces_in_place
    normalize_namespaces_in_place("path/to/file.hwpx")
"""

from __future__ import annotations

import sys
from pathlib import Path

from hwpx_toolkit import normalize_namespaces_in_place


def _run(args: list[str]) -> int:
    if len(args) != 2:
        sys.stderr.write("Usage: python hwpx_ns_repair.py <file.hwpx>\n")
        return 2

    target = Path(args[1])
    if not target.exists():
        sys.stderr.write(f"error: path not found: {target}\n")
        return 1
    if not target.is_file():
        sys.stderr.write(f"error: not a regular file: {target}\n")
        return 1

    try:
        normalize_namespaces_in_place(target)
    except Exception as exc:  # noqa: BLE001 — CLI surface, convert to message
        sys.stderr.write(f"error: {exc}\n")
        return 1

    sys.stdout.write(f"ok: {target}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run(sys.argv))
