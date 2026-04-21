---
name: hwpx
description: "한글(한컴오피스) HWPX 문서를 생성·읽기·편집·양식 치환하는 스킬. 'hwpx', 'HWPX', '한글 파일', '한글 문서', '한글 보고서', '공문', '기안문', '한글로 작성', '한글 양식 채워줘' 같은 표현이 보이면 이 스킬을 쓴다. HWPX 는 한컴에서 만든 개방형 OWPML(KS X 6101) 포맷으로 내부가 ZIP + XML 구조이다. `python-hwpx` 라이브러리와 이 스킬에 포함된 `hwpx_toolkit` 모듈을 함께 쓴다. 일반 워드(.docx)는 docx 스킬을 사용할 것."
---

# HWPX 스킬 — 생성·편집·양식 치환

## 이 스킬이 해결하는 문제

- 한글 보고서를 **스켈레톤** 위에서 채워 넣어 PDF 로 뽑을 수준까지 만든다.
- 공문(기안문) 을 법정 항목 체계와 날짜 형식에 맞춰 새로 작성한다.
- 이미 존재하는 .hwpx 파일을 열어 **표지·본문·작성일** 같은 특정 위치의
  텍스트만 안전하게 바꿔서 저장한다.
- ZIP 안쪽에 손을 대더라도 치환이 실패하면 원본이 손상되지 않게, Hangul
  Viewer(특히 macOS) 에서 빈 페이지로 뜨지 않게 후처리까지 끝낸다.

---

## 1. 환경

### 1-0. 자가 점검 — 스킬 호출 직전 (필수)

HWPX 관련 요청을 받으면 **실제 편집 코드를 실행하기 직전에** 아래 두
가지를 이 순서대로 점검하고, 빠져 있는 것만 채운다. 둘 다 멱등이므로
매 사용 전 검사해도 무해하다. 사용자가 수동 설치를 이미 했다면
대부분 no-op 으로 끝난다.

```bash
# (1) python-hwpx 가 import 가능한가
#     실패할 때만 pip 로 설치. PEP 668 면 --break-system-packages 재시도.
python -c "import hwpx" 2>/dev/null \
    || pip install python-hwpx \
    || pip install python-hwpx --break-system-packages

# (2) 빌트인 스켈레톤이 존재하는가 (빌트인 경로로 보고서를 만들 때만)
#     SKILL_DIR = 이 SKILL.md 가 있는 디렉터리.
test -f "$SKILL_DIR/assets/report-skeleton.hwpx" \
    || python "$SKILL_DIR/scripts/build_report_skeleton.py"
```

PowerShell 환경에서도 흐름은 동일하다 — `python -c "import hwpx"` 의
exit code 로 분기하고 `Test-Path` 로 스켈레톤을 점검한다. `python` 이
`python3` 로만 잡히는 macOS·Linux 환경에서는 아래 규칙에 따라
`sys.executable` 또는 `python3` 로 대체한다.

사용자 업로드 양식만 쓸 예정이면 (2) 는 건너뛴다 (Section 2 참고).
사용자 환경이 가상환경 없이 PEP 668 로 보호된 경우 (1) 의 세 번째
분기로 `--break-system-packages` 가 자동으로 시도된다.

### 1-1. 파이썬 실행 관례

파이썬 인터프리터를 호출할 때는 항상 `sys.executable` 을 쓴다 (macOS·Linux
에서 `python` 이 `python3` 일 수 있음).

스킬 내부의 경로는 전부 상대 경로 + `pathlib` 기반이다. Windows · macOS ·
Linux 모두에서 동일하게 동작하도록 의도했다.

---

## 2. ⚠️ 어떤 양식을 쓸지 먼저 결정한다

HWPX 를 만들 때 **가장 먼저** 결정할 것은 "어떤 양식 위에서 시작할
것인가" 이다. 다음 순서를 어기지 않는다.

### Step 1 — 사용자가 .hwpx 양식을 업로드했는가?

업로드한 파일이 있으면 **무조건** 그 파일을 스켈레톤으로 쓴다.
"이 양식으로", "이 파일 기반으로" 와 같은 말이 있으면 100 % 그 파일이다.
빌트인 스켈레톤을 끌어오지 않는다.

### Step 2 — 업로드가 없으면 빌트인 스켈레톤으로 시작

빌트인 경로:

```
assets/report-skeleton.hwpx          (보고서)
```

스켈레톤이 존재하지 않으면 한 번만 **직접 생성**한다 (원본 바이너리를
저장소에 두지 않는다 — 아래 [4. 스켈레톤 생성] 참조).

### Step 3 — `HwpxDocument.new()` 는 "짧은 공문·메모" 에만

표지·목차·섹션 바 같은 디자인 요소가 필요한 문서를 `new()` 로 짜서
만들려 하지 않는다. 재현이 번거롭고 실패율이 높다. 아주 짧은
기안문이나 한두 문단짜리 메모라면 허용.

---

## 3. 핵심 API — `HwpxPackage`

이 스킬은 `scripts/hwpx_toolkit.py` 에 패키지 편집용 컨텍스트 매니저를
제공한다. 원본 ZIP 을 메모리에 적재한 뒤 치환/정규화하고 **원자적으로
커밋** 한다(임시 파일 → `os.replace`).

```python
import sys, os
sys.path.insert(0, os.path.join(SKILL_DIR, "scripts"))   # 또는 PYTHONPATH
from hwpx_toolkit import HwpxPackage

with HwpxPackage.open("report.hwpx") as pkg:
    # (1) 모든 Contents/*.xml 에서 일괄 치환
    pkg.replace_all({
        "{{REPORT_TITLE}}": "2026 하반기 운영 계획",
        "{{REPORT_DATE}}":  "2026. 4. 21.",
    })

    # (2) 동일 마커를 본문에서 만나는 순서대로 다른 값으로
    pkg.replace_ordered("{{HEADING_L1}}", [
        "추진 배경", "현황 분석", "개선 방안",
    ])

    # (3) ns0/ns1 자동 prefix 를 한컴 표준(hh/hc/hp/hs) 로 정규화
    pkg.normalize_namespaces()

    # (4) 원자적으로 저장 (default = 원본 덮어쓰기)
    pkg.commit()                    # or pkg.commit("out.hwpx")
```

메서드 요약:

| 메서드                          | 용도                                                          |
|---------------------------------|---------------------------------------------------------------|
| `HwpxPackage.open(path)`        | ZIP 을 메모리로 적재                                          |
| `replace_all(mapping)`          | 모든 XML 파트에서 일괄 치환 (치환 합계 반환)                   |
| `replace_ordered(marker, vals)` | 같은 마커를 본문(section\*.xml)에서 순서대로 치환             |
| `normalize_namespaces()`        | `ns0`/`ns1` → `hh`/`hc`/`hp`/`hs` 재매핑 (변경된 파트 수 반환) |
| `commit(dest=None)`             | 임시파일 → `os.replace` 로 원자적 저장                        |
| `read_text(entry_name)`         | 진단용. 특정 XML 파트의 원문 확인                             |
| `xml_parts()`                   | Contents/*.xml 엔트리 이름 순회                               |

기본 옵션:

- 치환 값은 자동으로 **XML 이스케이프** 된다. 값 자체에 마크업을 넣어야
  하는 경우에만 `HwpxConfig(escape_values=False)` 로 새 인스턴스를
  만들어 쓴다.
- ZIP 엔트리 1 개 최대 허용 크기 = 50 MB (`HwpxConfig.max_entry_bytes`).
  압축 폭탄 방어용.
- 경로에 `..` 가 포함된 엔트리는 로드 단계에서 거부된다(Zip Slip 방어).

---

## 4. 스켈레톤(.hwpx) 새로 생성하기

이 저장소에는 **바이너리 스켈레톤을 커밋하지 않는다**. 다른 배포물에서
그대로 가져온 파일을 포함하지 않기 위한 정책이다. 대신 `python-hwpx` 를
이용해 **즉석에서 생성**한다.

```bash
# 기본 경로(assets/report-skeleton.hwpx)에 생성
python scripts/build_report_skeleton.py

# 다른 위치에 저장
python scripts/build_report_skeleton.py path/to/custom.hwpx
```

생성 결과에 박히는 마커 요약:

| 마커              | 치환 방식              | 기본 생성 수량 |
|-------------------|------------------------|----------------|
| `{{ORG_NAME}}`    | `replace_all`          | 1              |
| `{{REPORT_TITLE}}`| `replace_all`          | 1              |
| `{{REPORT_DATE}}` | `replace_all`          | 1              |
| `{{DOC_SUBTITLE}}`| `replace_all`          | 1              |
| `{{HEADING_L1}}`  | `replace_ordered`      | 5              |
| `{{HEADING_L2}}`  | `replace_ordered`      | 6              |
| `{{BODY_L3}}`     | `replace_ordered`      | 8              |
| `{{NOTE_L4}}`     | `replace_ordered`      | 6              |

수량을 바꾸고 싶으면 `scripts/build_report_skeleton.py` 의 `BODY_SLOTS`
값을 수정한 뒤 다시 실행한다.

---

## 5. 워크플로우

### 5-1. 빌트인 스켈레톤으로 보고서 만들기

```python
import shutil
from pathlib import Path
from hwpx_toolkit import HwpxPackage

SKILL_DIR = Path(__file__).resolve().parent        # 또는 하드코딩된 스킬 루트
SKELETON  = SKILL_DIR / "assets" / "report-skeleton.hwpx"
OUTPUT    = Path.cwd() / "report.hwpx"

# 1) 스켈레톤 복사
shutil.copy(SKELETON, OUTPUT)

# 2) 패키지 편집
with HwpxPackage.open(OUTPUT) as pkg:
    pkg.replace_all({
        "{{ORG_NAME}}":     "AI 정책국",
        "{{REPORT_TITLE}}": "2026 하반기 운영 계획",
        "{{REPORT_DATE}}":  "2026. 4. 21.",
        "{{DOC_SUBTITLE}}": "정책 방향 및 실행 계획",
    })

    pkg.replace_ordered("{{HEADING_L1}}", [
        "추진 배경", "현황 분석", "개선 방안", "기대 효과", "향후 일정",
    ])
    pkg.replace_ordered("{{HEADING_L2}}", [
        "전년 대비 변화",  "주요 지표 3종", "도입률 45 % 초과",
        "민원 처리 시간 단축", "2026 하반기 KPI", "예산 배정 기준",
    ])
    pkg.replace_ordered("{{BODY_L3}}", [...])        # 8 개
    pkg.replace_ordered("{{NOTE_L4}}", [...])        # 6 개

    # 3) 네임스페이스 정규화 + 원자적 저장
    pkg.normalize_namespaces()
    pkg.commit()
```

> `replace_ordered` 는 값이 모자라면 남은 마커를 **그대로 둔다**. 이는
> 디버깅/미완성 보고서에서 유용한 동작이지만, 배포 직전에는
> `ObjectFinder` 나 `pkg.read_text()` 로 남은 마커가 없는지 확인하는
> 것이 좋다.

### 5-2. 사용자 업로드 양식으로 채우기

사용자 양식은 우리가 만든 것이 아니므로 **어떤 플레이스홀더가 박혀
있는지 반드시 먼저 조사**한다.

```python
from pathlib import Path
import shutil
from hwpx import ObjectFinder        # 양식 내 텍스트 열람
from hwpx_toolkit import HwpxPackage

SOURCE = Path("user-template.hwpx")   # 사용자가 업로드한 파일
OUTPUT = Path("filled.hwpx")

# 1) 작업 사본으로 복사
shutil.copy(SOURCE, OUTPUT)

# 2) 텍스트 전수 조사 (필수)
for result in ObjectFinder(str(OUTPUT)).find_all(tag="t"):
    if result.text and result.text.strip():
        print(repr(result.text))

# 3) 조사 결과를 바탕으로 매핑 작성 (양식마다 다름)
mapping = {
    "양식에_실제로_박혀있던_제목_문구":  "실제 제목",
    "양식의_작성일_플레이스홀더":          "2026. 4. 21.",
    # ...
}

# 4) 치환 + 후처리
with HwpxPackage.open(OUTPUT) as pkg:
    pkg.replace_all(mapping)
    pkg.normalize_namespaces()
    pkg.commit()
```

### 5-3. 빈 문서에서 공문(기안문) 새로 작성

간단한 공문이면 `HwpxDocument.new()` 로 시작해도 된다. 규격/기호 체계는
`references/official-letter-guide.md` 를 따른다.

```python
from hwpx.document import HwpxDocument
from hwpx_toolkit import normalize_namespaces_in_place

doc = HwpxDocument.new()
doc.add_paragraph("1. 관련: 교육정책과-1234(2026. 2. 1.)")
doc.add_paragraph("2. 2026 년도 정보화 교육 실시를 다음과 같이 안내하오니 …")
doc.add_paragraph("  가. 일시: 2026. 3. 10.(화) 14:00 ∼ 16:00")
doc.add_paragraph("  나. 장소: 본관 대회의실")
doc.add_paragraph("  다. 대상: 전 직원")
doc.add_paragraph("")
doc.add_paragraph("붙임  2026학년도 정보화 교육 일정표 1부.  끝.")

doc.save("letter.hwpx")
normalize_namespaces_in_place("letter.hwpx")
```

---

## 6. ⚠️ 필수 후처리 — 네임스페이스 정규화

python-hwpx / ElementTree 로 저장한 .hwpx 는 `ns0`, `ns1` 같은 자동
prefix 를 남기는 경우가 있다. 이 상태 그대로 macOS Hangul Viewer 에서
열면 **본문이 빈 페이지로 보이는 증상**이 발생한다.

저장 직후 다음 중 한 방법으로 반드시 정규화한다.

**(A) 같은 프로세스에서 함수 호출 — 권장**

```python
from hwpx_toolkit import normalize_namespaces_in_place
normalize_namespaces_in_place("output.hwpx")
```

**(B) 별도 프로세스로 CLI 실행**

```python
import subprocess, sys, os
cli = os.path.join(SKILL_DIR, "scripts", "hwpx_ns_repair.py")
subprocess.run([sys.executable, cli, "output.hwpx"], check=True)
```

`HwpxPackage` 흐름을 끝까지 사용했다면 `pkg.normalize_namespaces()` +
`pkg.commit()` 로 이미 처리된다. 공문을 `HwpxDocument.save()` 로
만들었을 때만 위 후처리를 별도로 호출하면 된다.

---

## 7. 스타일 참고 문서

| 상황                         | 참고                                      |
|------------------------------|-------------------------------------------|
| 내부 보고용 보고서            | `references/report-writing-guide.md`     |
| 공문서·기안문                 | `references/official-letter-guide.md`    |
| 저수준 XML·네임스페이스·단위  | `references/hwpx-format-notes.md`        |

---

## 8. Quick Reference

| 하고 싶은 일                           | 접근                                                   |
|----------------------------------------|-------------------------------------------------------|
| 양식 보고서 생성                        | 스켈레톤 복사 → `HwpxPackage` 치환 → `commit()`        |
| 사용자 양식 채우기                      | ObjectFinder 로 조사 → 매핑 작성 → `HwpxPackage`       |
| 짧은 공문 새로 쓰기                     | `HwpxDocument.new()` + `normalize_namespaces_in_place` |
| 텍스트 검색/열람                        | `ObjectFinder`, `HwpxPackage.read_text`                |
| 표 셀 편집                              | `HwpxDocument.open()` + `table.set_cell_text`          |
| 머리글/바닥글                           | `HwpxDocument.set_header_text` / `set_footer_text`     |
| 네임스페이스 문제로 빈 페이지 표시       | `normalize_namespaces_in_place(path)`                  |

---

## 9. 주의사항

1. **양식 우선**: 사용자 업로드 > 빌트인 스켈레톤 > `HwpxDocument.new()`.
2. **ZIP-level 편집 > `HwpxDocument.open()`**: 라이브러리 버전별로
   복잡한 양식 파싱이 실패할 수 있다. `HwpxPackage` 사용이 안전.
3. **정규화 누락 = 빈 페이지**: 저장 후 반드시 네임스페이스 정규화.
4. **사용자 양식은 조사 먼저**: 어떤 플레이스홀더가 있는지 모른 채
   치환을 걸면 과치환·누락이 발생한다.
5. **`replace_ordered` 는 본문 전용**: 기본값 `sections_only=True` 는
   표지·머리말 영역에서 같은 마커가 섞여 들어가는 사고를 막기 위한
   안전장치이다. 전체 XML 대상으로 돌릴 땐 `sections_only=False`.
6. **공문 날짜 형식**: `2026-02-13` ❌ → `2026. 2. 13.` ✅ (월·일 앞 0 없음).
7. **글꼴은 외부 의존**: .hwpx 에 글꼴을 임베딩하지 않는다. 열람 환경에
   해당 글꼴이 없으면 치환 결과가 예상과 다를 수 있다.
8. **HWPX ↔ HWP**: 레거시 바이너리 `.hwp` 는 대상 외이다.
9. **보안 — XML 이스케이프**: 외부 입력을 치환 값으로 받을 때 기본
   이스케이프 동작(`escape_values=True`) 을 유지한다.
10. **보안 — 임시파일**: `HwpxPackage.commit` 은 `tempfile.mkstemp` 로
    예측 불가능한 스테이징 경로를 사용하며, 실패 시 자동으로 지운다.
11. **보안 — ZIP 엔트리 크기 제한**: 기본 50 MB. 커지려면
    `HwpxConfig(max_entry_bytes=…)` 를 명시적으로 설정.
12. **보안 — 경로 이탈 방어**: 로드 시 `..` 포함 엔트리를 거부한다.
13. **크로스 플랫폼**: 파이썬 실행은 `sys.executable`, 경로는
    `pathlib.Path` 또는 `os.path.join`.
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              