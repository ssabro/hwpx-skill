---
name: hwpx
description: "HWPX 문서(.hwpx 파일)를 생성, 읽기, 편집, 템플릿 치환하는 스킬. '한글 문서', 'hwpx', 'HWPX', '한글파일', '.hwpx 파일 만들어줘', 'HWP 문서 생성', '보고서', '공문', '기안문', '한글로 작성' 등의 키워드가 나오면 반드시 이 스킬을 사용할 것. 한글과컴퓨터(한컴)의 HWPX 포맷(KS X 6101/OWPML 기반, ZIP+XML 구조)을 python-hwpx 라이브러리로 다룬다. 보고서 양식이 필요하면 assets/ 폴더의 레퍼런스 템플릿을 활용한다. 일반 Word(.docx) 문서에는 docx 스킬을 사용할 것."
---

# HWPX 문서 생성·편집 스킬

## 개요

HWPX는 한컴오피스 한글의 개방형 문서 포맷이다. 내부는 **ZIP 패키지 + XML 파트** 구조이며, KS X 6101(OWPML) 표준에 기반한다. 이 스킬은 `python-hwpx` 라이브러리를 사용하여 HWPX 문서를 프로그래밍 방식으로 생성·편집·템플릿 치환한다.

## 설치

```bash
# venv 또는 conda 환경 권장
pip install python-hwpx

# 시스템 Python에 직접 설치 시 (Debian/Ubuntu 등 PEP 668 환경)
pip install python-hwpx --break-system-packages
```

---

## ⚠️⚠️⚠️ 최우선 규칙: 양식(템플릿) 선택 정책 ⚠️⚠️⚠️

> **HWPX 문서를 만들 때 반드시 아래 순서를 따른다. 예외 없음.**

### 1단계: 사용자 업로드 양식이 있는가?

사용자가 `.hwpx` 양식 파일을 업로드했다면 **반드시 해당 파일을 템플릿으로 사용**한다.
- 사용자가 제공한 `.hwpx` 파일 경로를 확인
- 있다면 → 그 파일을 복사하여 템플릿으로 사용 (기본 양식 무시)
- 사용자가 "이 양식으로 만들어줘", "이 파일 기반으로" 등의 표현을 쓰면 100% 해당 파일 사용

### 2단계: 기본 제공 양식 사용

사용자 업로드 양식이 없으면 **반드시 기본 제공 양식**을 사용한다:
- 보고서 → `assets/report-template.hwpx`
- (향후 추가될 다른 양식들도 이 규칙 적용)

### 3단계: HwpxDocument.new()는 최후의 수단

`HwpxDocument.new()`로 빈 문서를 만드는 것은 **아주 단순한 메모·목록 수준의 문서에만** 허용한다. 보고서, 공문, 기안문 등 양식이 필요한 문서는 절대 `new()`로 만들지 않는다.

---

## ⚠️ 양식 활용 시 필수 워크플로우 (모든 경우에 적용)

어떤 양식을 쓰든(사용자 업로드든, 기본 제공이든) 아래 워크플로우를 따른다:

```
[1] 양식 파일을 작업 디렉토리로 복사
     ↓
[2] ObjectFinder로 양식 내 텍스트 전수 조사
     ↓
[3] 플레이스홀더 목록 작성 (어떤 텍스트를 뭘로 바꿀지 매핑)
     ↓
[4] ZIP-level 전체 치환 (표 내부 포함)
     ↓  (동일 플레이스홀더가 여러 번 나오면 순차 치환 사용)
[5] 네임스페이스 후처리 (fix_namespaces.py)
     ↓
[6] ObjectFinder로 치환 결과 검증
     ↓
[7] 결과 파일을 사용자가 지정한 출력 경로로 복사
```

### 핵심: HwpxDocument.open()은 사용하지 않는다

`python-hwpx` 버전에 따라 `HwpxDocument.open()`이 복잡한 양식 파일을 파싱하지 못할 수 있다. **ZIP-level 치환만 사용**하는 것이 안전하다.

---

## ZIP-level 치환 함수 (직접 구현)

`hwpx_replace` 모듈은 별도로 존재하지 않으므로 아래 함수를 직접 코드에 포함한다:

### 일괄 치환 (동일 텍스트를 모두 같은 값으로)

```python
import zipfile, os, tempfile
from xml.sax.saxutils import escape as xml_escape

MAX_ENTRY_SIZE = 50 * 1024 * 1024  # ZIP 엔트리 최대 50MB

def _is_safe_zip_entry(filename):
    """ZIP 엔트리 경로 안전성 검증 (Zip Slip 방어)"""
    if filename.startswith(("/", "\\")):
        return False
    return ".." not in filename.split("/") and ".." not in filename.split("\\")

def zip_replace(src_path, dst_path, replacements, escape_xml=True):
    """HWPX ZIP 내 모든 XML에서 텍스트 치환 (표 내부 포함)

    Args:
        escape_xml: True이면 치환 값의 XML 특수문자(<, >, &)를 이스케이핑한다.
                    플레이스홀더에 XML 태그를 넣어야 하는 경우에만 False로 설정.
    """
    target_dir = os.path.dirname(os.path.abspath(dst_path))
    fd, tmp = tempfile.mkstemp(suffix=".hwpx.tmp", dir=target_dir)
    os.close(fd)
    try:
        with zipfile.ZipFile(src_path, "r") as zin:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    if not _is_safe_zip_entry(item.filename):
                        raise ValueError(f"Unsafe ZIP entry: {item.filename}")
                    if item.file_size > MAX_ENTRY_SIZE:
                        raise ValueError(f"ZIP entry too large: {item.filename}")
                    data = zin.read(item.filename)
                    if item.filename.startswith("Contents/") and item.filename.endswith(".xml"):
                        text = data.decode("utf-8")
                        for old, new in replacements.items():
                            safe_new = xml_escape(new) if escape_xml else new
                            text = text.replace(old, safe_new)
                        data = text.encode("utf-8")
                    zout.writestr(item, data)
        os.replace(tmp, dst_path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
```

### 순차 치환 (동일 플레이스홀더를 순서대로 다른 값으로)

```python
def zip_replace_sequential(src_path, dst_path, old, new_list, escape_xml=True):
    """section XML에서 old를 순서대로 new_list 값으로 하나씩 치환"""
    target_dir = os.path.dirname(os.path.abspath(dst_path))
    fd, tmp = tempfile.mkstemp(suffix=".hwpx.tmp", dir=target_dir)
    os.close(fd)
    try:
        with zipfile.ZipFile(src_path, "r") as zin:
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    if not _is_safe_zip_entry(item.filename):
                        raise ValueError(f"Unsafe ZIP entry: {item.filename}")
                    if item.file_size > MAX_ENTRY_SIZE:
                        raise ValueError(f"ZIP entry too large: {item.filename}")
                    data = zin.read(item.filename)
                    if "section" in item.filename and item.filename.endswith(".xml"):
                        text = data.decode("utf-8")
                        for new_val in new_list:
                            safe_val = xml_escape(new_val) if escape_xml else new_val
                            text = text.replace(old, safe_val, 1)  # 1번만 치환
                        data = text.encode("utf-8")
                    zout.writestr(item, data)
        os.replace(tmp, dst_path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
```

---

## 양식 내 텍스트 전수 조사 방법

```python
from hwpx import ObjectFinder

finder = ObjectFinder("양식파일.hwpx")
results = finder.find_all(tag="t")
for r in results:
    if r.text and r.text.strip():
        print(repr(r.text))
```

이 결과를 보고 어떤 텍스트가 플레이스홀더인지 파악한 후, 치환 매핑을 작성한다.

---

## 기본 양식(report-template.hwpx) 활용 가이드

### 양식 구조

```
1쪽: 표지      → 기관명(30pt) + 보고서 제목(25pt) + 작성일(25pt)
2쪽: 목차      → 로마숫자(Ⅰ~Ⅴ) + 제목 + 페이지, 붙임/참고
3쪽~: 본문     → 결재란 + 제목(22pt) + 섹션 바(Ⅰ~Ⅳ) + □○―※ 계층 본문
```

### 본문 기호 체계 (공문서와 완전히 다름!)

```
1단계:  □    (HY헤드라인M 16pt, 문단 위 15)
2단계:  ○    (휴먼명조 15pt, 문단 위 10)
3단계:  ―    (휴먼명조 15pt, 문단 위 6)
4단계:  ※    (한양중고딕 13pt, 문단 위 3)
```

### 치환 가능한 플레이스홀더 목록

| 플레이스홀더 | 위치 | 치환 대상 | 치환 방법 |
|------------|------|----------|----------|
| `브라더 공기관` | 표지 1줄 | 기관명 | 일괄 치환 |
| `기본 보고서 양식` | 표지 2줄 | 보고서 제목 | 일괄 치환 |
| `2024. 5. 23.` | 표지 작성일 | 실제 작성일 | 일괄 치환 |
| `제 목` | 본문 페이지 제목 | 보고서 제목 | 일괄 치환 |
| `. 개요` 등 | 목차 항목 | 실제 목차 제목 | 일괄 치환 |
| ` 추진 배경` 등 | 섹션 바 제목 | 실제 섹션 제목 | 일괄 치환 |
| `헤드라인M 폰트 16포인트(문단 위 15)` | □ 본문 (8개) | 1단계 내용 | **순차 치환** |
| `  ○ 휴면명조 15포인트(문단위 10)` | ○ 본문 (8개) | 2단계 내용 | **순차 치환** |
| `   ― 휴면명조 15포인트(문단 위 6)` | ― 본문 (8개) | 3단계 내용 | **순차 치환** |
| `     ※ 중고딕 13포인트(문단 위 3)` | ※ 주석 (7개) | 4단계 참조 | **순차 치환** |
| `  1. 세부내용` / `  2. 세부내용` | 붙임/참고 | 첨부 목록 | 일괄 치환 |

### 기본 양식 사용 예시 (전체 코드)

```python
import shutil, sys, os

# 스킬 기본 디렉토리 (이 스킬이 설치된 경로)
SKILL_DIR = os.path.dirname(os.path.abspath(__file__))  # 또는 직접 지정
TEMPLATE = os.path.join(SKILL_DIR, "assets", "report-template.hwpx")
WORK = os.path.join(os.getcwd(), "report.hwpx")
shutil.copy(TEMPLATE, WORK)

# 1. 표지 + 목차 + 섹션 바 + 제목 (일괄 치환)
zip_replace(WORK, WORK, {
    "브라더 공기관": "실제 기관명",
    "기본 보고서 양식": "실제 보고서 제목",
    "2024. 5. 23.": "2026. 2. 13.",
    "제 목": "실제 보고서 제목",
    ". 개요": ". 실제 목차1",
    ". 추진배경": ". 실제 목차2",
    # ... 나머지 목차, 섹션 바 치환
})

# 2. □ 항목 (순차 치환 — 8개)
zip_replace_sequential(WORK, WORK,
    "헤드라인M 폰트 16포인트(문단 위 15)",
    ["첫번째 □ 내용", "두번째 □ 내용", ...]
)

# 3. ○, ―, ※ 항목도 각각 순차 치환
# ...

# 4. 네임스페이스 후처리 (필수!)
import subprocess
fix_script = os.path.join(SKILL_DIR, "scripts", "fix_namespaces.py")
subprocess.run([sys.executable, fix_script, WORK], check=True)

# 5. 결과 검증
from hwpx import ObjectFinder
finder = ObjectFinder(WORK)
for r in finder.find_all(tag="t"):
    if r.text and r.text.strip():
        print(r.text)
```

---

## 사용자 업로드 양식 활용 가이드

사용자가 자신만의 `.hwpx` 양식을 업로드한 경우:

```python
import shutil, subprocess, sys, os

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))  # 또는 직접 지정

# 1. 사용자 양식을 작업 디렉토리로 복사
USER_TEMPLATE = "사용자양식.hwpx"  # 사용자가 제공한 경로
WORK = os.path.join(os.getcwd(), "report.hwpx")
shutil.copy(USER_TEMPLATE, WORK)

# 2. 양식 내 텍스트 전수 조사 (★ 필수 단계!)
from hwpx import ObjectFinder
finder = ObjectFinder(WORK)
for r in finder.find_all(tag="t"):
    if r.text and r.text.strip():
        print(repr(r.text))

# 3. 조사 결과를 바탕으로 치환 매핑 작성
#    (양식마다 플레이스홀더가 다르므로 반드시 조사 후 진행)

# 4. ZIP-level 치환 적용
zip_replace(WORK, WORK, {
    "양식의 기존 텍스트": "실제 내용",
    # ...
})

# 동일 플레이스홀더가 여러 번 → 순차 치환
zip_replace_sequential(WORK, WORK, "반복되는 텍스트", ["값1", "값2", ...])

# 5. 네임스페이스 후처리
fix_script = os.path.join(SKILL_DIR, "scripts", "fix_namespaces.py")
subprocess.run([sys.executable, fix_script, WORK], check=True)

# 6. 치환 결과 검증
finder = ObjectFinder(WORK)
for r in finder.find_all(tag="t"):
    if r.text and r.text.strip():
        print(r.text)
```

---

## 문서 유형별 스타일 가이드

### 보고서(내부 보고용) 작성 시

→ **`references/report-style.md`** 를 먼저 읽고 따를 것

### 공문서(기안문) 작성 시

→ **`references/official-doc-style.md`** 를 먼저 읽고 따를 것

### 저수준 XML 조작이 필요한 경우

→ **`references/xml-internals.md`** 를 읽을 것

---

## ⚠️ 필수 후처리: 네임스페이스 수정

> **가장 중요한 단계. 빠뜨리면 한글 Viewer에서 빈 페이지로 표시된다.**

ZIP-level 치환 후 또는 `doc.save()` 후 반드시 실행:

```python
# 방법 1: 직접 import (같은 Python 프로세스 — 권장)
from fix_namespaces import fix_hwpx_namespaces
fix_hwpx_namespaces("output.hwpx")

# 방법 2: subprocess로 실행
import subprocess, sys, os
fix_script = os.path.join(SKILL_DIR, "scripts", "fix_namespaces.py")
subprocess.run([sys.executable, fix_script, "output.hwpx"], check=True)
```

> 주의: `sys.executable`을 사용해야 현재 Python 인터프리터와 동일한 환경에서 실행된다. `"python"` 하드코딩은 macOS/Linux에서 `python3`만 존재하는 경우 실패한다.

---

## Quick Reference

| 작업 | 접근 방식 |
|------|----------|
| 보고서/공문/양식 문서 생성 | **양식 파일 + ZIP-level 치환** (★ 권장) |
| 아주 단순한 문서 | `HwpxDocument.new()` → `.save()` → 후처리 |
| 표(테이블) 추가 | `doc.add_table(rows, cols)` → `set_cell_text()` |
| 머리글/바닥글 | `doc.set_header_text()` / `doc.set_footer_text()` |
| 텍스트 검색/추출 | `ObjectFinder(filepath)` |
| 셀 병합 | `table.merge_cells(row1, col1, row2, col2)` |

---

## 주의사항

1. **양식 우선**: 사용자 업로드 양식 > 기본 제공 양식 > HwpxDocument.new()
2. **ZIP-level 치환 우선**: HwpxDocument.open()보다 ZIP-level 치환이 안전하고 호환성이 높다
3. **네임스페이스 후처리 필수**: 모든 저장/치환 후 `fix_namespaces.py` 실행
4. **양식 텍스트 조사 필수**: 치환 전에 반드시 ObjectFinder로 텍스트 전수 조사
5. **순차 치환 주의**: 동일 플레이스홀더가 여러 번 나오면 `zip_replace_sequential` 사용
6. **레이아웃 충실도**: python-hwpx는 레이아웃 엔진이 아님. 페이지 나눔은 한글 앱이 결정
7. **글꼴 임베딩**: 생성 HWPX에 글꼴 미포함. 열람 환경에 해당 글꼴 필요
8. **공문서 날짜 형식**: `2026-02-13`이 아닌 `2026. 2. 13.` (월·일 앞 0 생략)
9. **HWPX ↔ HWP**: python-hwpx는 HWPX만 처리. 레거시 `.hwp`는 별도 도구 필요
10. **fix_namespaces 호출법**: 직접 import(`from fix_namespaces import fix_hwpx_namespaces`) 또는 `subprocess.run([sys.executable, ...])` 사용
11. **크로스 플랫폼**: 경로에 `os.path.join()` 사용, Python 실행에 `sys.executable` 사용
12. **보안 — XML 이스케이핑**: 사용자 입력이 치환 값에 들어갈 때 `xml_escape()`로 `<`, `>`, `&` 이스케이핑 (기본 활성화)
13. **보안 — 임시파일**: `tempfile.mkstemp()`로 예측 불가능한 임시파일 생성. `파일명.tmp` 같은 예측 가능한 경로 사용 금지
14. **보안 — ZIP bomb 방어**: ZIP 엔트리 크기를 검증하여 메모리 소진 공격 방지 (기본 50MB 제한)
15. **보안 — Zip Slip 방어**: ZIP 엔트리의 `..` 경로 순회를 검증하여 디렉토리 탈출 방지