"""HWPX 편집 툴킷.

한 개의 .hwpx 패키지를 메모리에 적재해서 텍스트 파트(Contents/*.xml)에
문자열 치환과 네임스페이스 정규화를 수행한 뒤 원자적으로 커밋한다.

외부 표면은 :class:`HwpxPackage` 하나로 통일되어 있으며, 보조
API(:func:`normalize_namespaces_in_place`)는 짧은 일회성 호출을 위한
편의 함수이다.

설계 원칙:
    - ZIP 스트림을 직접 건드리는 대신 한 번 읽어 dict로 들고 있다가
      commit 시점에 한 덩어리로 재직렬화한다. 치환 실패 시 원본은
      건드리지 않는다.
    - 커밋은 동일 디렉터리에 스테이징 파일을 쓴 뒤 `os.replace`로
      교체하므로 중단되어도 부분 쓰기 상태가 남지 않는다.
    - ZIP 엔트리 크기와 경로 구성 요소를 검증해 압축 폭탄/경로
      이탈 공격을 차단한다.
"""

from __future__ import annotations

import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence
from xml.sax.saxutils import escape as _xml_escape

__all__ = [
    "HwpxPackage",
    "HwpxConfig",
    "normalize_namespaces_in_place",
]


# OWPML 2011(KS X 6101) 표준 네임스페이스 → 한컴 Viewer가 기대하는 canonical prefix.
_CANONICAL_PREFIXES: Mapping[str, str] = {
    "http://www.hancom.co.kr/hwpml/2011/head":      "hh",
    "http://www.hancom.co.kr/hwpml/2011/core":      "hc",
    "http://www.hancom.co.kr/hwpml/2011/paragraph": "hp",
    "http://www.hancom.co.kr/hwpml/2011/section":   "hs",
}

# ZIP 단일 엔트리 압축 해제 허용 상한. 너무 커지면 메모리 공격 여지.
_DEFAULT_ENTRY_CEILING_BYTES = 50 * 1024 * 1024

_CONTENTS_PREFIX = "Contents/"
_SECTION_TOKEN = "section"
_NS_ALIAS_RE = re.compile(r'xmlns:(ns\d+)="([^"]+)"')
_PATH_SPLIT_RE = re.compile(r"[\\/]+")


@dataclass(frozen=True)
class HwpxConfig:
    """:class:`HwpxPackage` 동작을 제어하는 설정값."""

    max_entry_bytes: int = _DEFAULT_ENTRY_CEILING_BYTES
    escape_values: bool = True


def _assert_safe_entry(name: str) -> None:
    if not name:
        raise ValueError("Empty ZIP entry name")
    if name[0] in ("/", "\\"):
        raise ValueError(f"Absolute ZIP entry rejected: {name!r}")
    if any(part == ".." for part in _PATH_SPLIT_RE.split(name)):
        raise ValueError(f"Path-traversal ZIP entry rejected: {name!r}")


def _render(value: str, escape: bool) -> str:
    return _xml_escape(value) if escape else value


def _is_contents_xml(entry_name: str) -> bool:
    return entry_name.startswith(_CONTENTS_PREFIX) and entry_name.endswith(".xml")


def _is_section_xml(entry_name: str) -> bool:
    return _SECTION_TOKEN in entry_name and entry_name.endswith(".xml")


class HwpxPackage:
    """컨텍스트 매니저 스타일의 HWPX 편집 핸들.

    일반적인 사용:

        with HwpxPackage.open("report.hwpx") as pkg:
            pkg.replace_all({"{{title}}": "Q2 리뷰"})
            pkg.replace_ordered("[ITEM]", ["첫째", "둘째", "셋째"])
            pkg.normalize_namespaces()
            pkg.commit()                      # 원본 덮어쓰기
            # pkg.commit("copy.hwpx")        # 다른 경로로 저장

    인스턴스는 :meth:`open` 또는 `with HwpxPackage.open(...)` 형태로만
    생성하는 것을 권장한다. 직접 `__init__` 호출 후 :meth:`load`를
    수동으로 부르는 것도 허용된다.
    """

    def __init__(self, source: str | os.PathLike[str], config: HwpxConfig | None = None):
        self._source = Path(source)
        self._config = config or HwpxConfig()
        self._entries: list[zipfile.ZipInfo] = []
        self._payloads: dict[str, bytes] = {}
        self._loaded = False

    # --------------------------------------------------------------- lifecycle

    @classmethod
    def open(
        cls,
        path: str | os.PathLike[str],
        config: HwpxConfig | None = None,
    ) -> "HwpxPackage":
        pkg = cls(path, config)
        pkg.load()
        return pkg

    def __enter__(self) -> "HwpxPackage":
        if not self._loaded:
            self.load()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        # 리소스 자체는 메모리뿐이므로 별도 해제가 필요 없다.
        self._loaded = False

    def load(self) -> None:
        """.hwpx(ZIP)을 읽어 모든 엔트리를 메모리에 적재한다."""
        with zipfile.ZipFile(self._source, "r") as archive:
            for info in archive.infolist():
                _assert_safe_entry(info.filename)
                if info.file_size > self._config.max_entry_bytes:
                    raise ValueError(
                        f"ZIP entry exceeds ceiling "
                        f"({info.file_size} > {self._config.max_entry_bytes}): "
                        f"{info.filename!r}"
                    )
                self._entries.append(info)
                self._payloads[info.filename] = archive.read(info.filename)
        self._loaded = True

    def commit(self, destination: str | os.PathLike[str] | None = None) -> Path:
        """현재 상태를 ``destination``(없으면 원본)으로 원자적으로 기록한다."""
        if not self._loaded:
            raise RuntimeError("HwpxPackage is not loaded; call .load() first")

        target = Path(destination) if destination is not None else self._source
        target = target.resolve()
        target.parent.mkdir(parents=True, exist_ok=True)

        fd, staged = tempfile.mkstemp(prefix=".hwpx-", suffix=".tmp", dir=target.parent)
        os.close(fd)
        staged_path = Path(staged)
        try:
            with zipfile.ZipFile(staged_path, "w", zipfile.ZIP_DEFLATED) as writer:
                for info in self._entries:
                    writer.writestr(info, self._payloads[info.filename])
            os.replace(staged_path, target)
        except Exception:
            if staged_path.exists():
                try:
                    staged_path.unlink()
                except OSError:
                    pass
            raise
        return target

    # ---------------------------------------------------------------- editors

    def replace_all(self, mapping: Mapping[str, str]) -> int:
        """Contents/*.xml 전체에서 키를 값으로 일괄 치환한다.

        반환값은 치환이 실제로 발생한 누적 횟수이다. 순서가 있는
        다중 플레이스홀더에는 :meth:`replace_ordered`를 쓴다.
        """
        if not mapping:
            return 0

        hits = 0
        for entry_name in self._payloads:
            if not _is_contents_xml(entry_name):
                continue
            original = self._payloads[entry_name].decode("utf-8")
            updated = original
            for needle, value in mapping.items():
                if not needle:
                    continue
                rendered = _render(value, self._config.escape_values)
                occurrences = updated.count(needle)
                if occurrences:
                    updated = updated.replace(needle, rendered)
                    hits += occurrences
            if updated != original:
                self._payloads[entry_name] = updated.encode("utf-8")
        return hits

    def replace_ordered(
        self,
        placeholder: str,
        values: Sequence[str],
        *,
        sections_only: bool = True,
    ) -> int:
        """동일 ``placeholder``를 만나는 순서대로 ``values`` 원소로 하나씩 바꾼다.

        기본적으로 section*.xml만 대상으로 하므로(=본문 영역) 표지/머리말에서
        같은 문자열이 오염되는 사고를 피한다. 전체 XML에 걸치고 싶으면
        ``sections_only=False``.
        """
        if not placeholder or not values:
            return 0

        pending = list(values)
        applied = 0
        for entry_name in self._payloads:
            if not pending:
                break
            eligible = _is_section_xml(entry_name) if sections_only else _is_contents_xml(entry_name)
            if not eligible:
                continue

            text = self._payloads[entry_name].decode("utf-8")
            parts: list[str] = []
            cursor = 0
            while pending:
                hit = text.find(placeholder, cursor)
                if hit < 0:
                    break
                parts.append(text[cursor:hit])
                parts.append(_render(pending.pop(0), self._config.escape_values))
                cursor = hit + len(placeholder)
                applied += 1
            if parts:
                parts.append(text[cursor:])
                self._payloads[entry_name] = "".join(parts).encode("utf-8")
        return applied

    def normalize_namespaces(self) -> int:
        """자동 생성 ``ns0``/``ns1``/... prefix를 한컴 canonical prefix로 치환.

        반환값은 변경이 가해진 XML 파트 개수. 이 단계는 python-hwpx나
        ElementTree가 저장한 파일을 Hangul Viewer(특히 macOS 빌드)에서
        정상 표시하기 위해 필요하다.
        """
        mutated_parts = 0
        for entry_name in self._payloads:
            if not _is_contents_xml(entry_name):
                continue
            text = self._payloads[entry_name].decode("utf-8")

            rename: dict[str, str] = {}
            for alias, uri in _NS_ALIAS_RE.findall(text):
                canonical = _CANONICAL_PREFIXES.get(uri)
                if canonical:
                    rename[alias] = canonical
            if not rename:
                continue

            for alias, canonical in rename.items():
                text = text.replace(f'xmlns:{alias}=', f'xmlns:{canonical}=')
                text = text.replace(f'<{alias}:',     f'<{canonical}:')
                text = text.replace(f'</{alias}:',    f'</{canonical}:')

            self._payloads[entry_name] = text.encode("utf-8")
            mutated_parts += 1
        return mutated_parts

    # --------------------------------------------------------------- accessors

    def xml_parts(self) -> Iterable[str]:
        """Contents/*.xml 엔트리 이름을 순회한다."""
        for name in self._payloads:
            if _is_contents_xml(name):
                yield name

    def read_text(self, entry_name: str) -> str:
        """임의 엔트리의 UTF-8 텍스트를 반환한다."""
        return self._payloads[entry_name].decode("utf-8")


# ----------------------------------------------------------------- shortcuts

def normalize_namespaces_in_place(path: str | os.PathLike[str]) -> Path:
    """``path`` 파일의 네임스페이스를 정규화하고 같은 경로로 저장한다."""
    with HwpxPackage.open(path) as pkg:
        pkg.normalize_namespaces()
        return pkg.commit()
