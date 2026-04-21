# hwpx-skill

Claude Code 용 한글(HWPX) 문서 생성·편집 스킬.
`python-hwpx` 와 이 프로젝트의 `hwpx_toolkit` 모듈을 함께 써서
한글 보고서·공문서를 생성하고, 스켈레톤 위에 플레이스홀더 치환을
수행하며, 편집된 ZIP 을 원자적으로 커밋한다. 한컴 Viewer 가 요구하는
네임스페이스 prefix 정규화까지 포함한다.

## 프로젝트 구성

```
hwpx-skill/
├─ SKILL.md                               # Claude 가 로드하는 스킬 본문
├─ README.md                              # 이 파일
├─ LICENSE                                # MIT
├─ scripts/
│  ├─ hwpx_toolkit.py                     # 편집 코어 (HwpxPackage)
│  ├─ hwpx_ns_repair.py                   # 네임스페이스 정규화 CLI
│  └─ build_report_skeleton.py            # 기본 보고서 스켈레톤 생성기
├─ assets/                                # (비어 있음 — 빌드 시 채움)
├─ references/
│  ├─ hwpx-format-notes.md                # 내부 포맷/네임스페이스/HWPUNIT 메모
│  ├─ report-writing-guide.md             # 내부 보고용 보고서 규격
│  └─ official-letter-guide.md            # 공문(기안문) 규격
└─ evals/
   └─ eval-cases.json                     # 평가 케이스
```

바이너리 템플릿은 저장소에 커밋하지 않는다. 필요할 때 아래의
`scripts/build_report_skeleton.py` 로 그때그때 생성한다.

## 설치

### A) Claude Code 플러그인으로 설치 (권장)

이 저장소는 Claude Code 마켓플레이스 매니페스트(`.claude-plugin/marketplace.json`)
를 포함하므로, 수동 복사 없이 Claude Code 슬래시 명령으로 바로 설치할 수 있다.

```text
/plugin marketplace add ssabro/hwpx-skill
/plugin install hwpx-skill@ssabro-skills
```

업데이트가 필요하면:

```text
/plugin marketplace update ssabro-skills
```

설치 후 Python 의존성(`python-hwpx`)은 아래 "B) 수동 설치" 의 1 단계를 참고한다.

### B) 수동 설치

#### 1) 저장소 내려받기

```bash
# git 으로 클론 (권장 — 이후 git pull 로 업데이트 가능)
git clone https://github.com/ssabro/hwpx-skill.git
cd hwpx-skill
```

git 이 없거나 특정 시점만 쓰고 싶다면 ZIP 아카이브를 받아도 된다:

```bash
# macOS / Linux
curl -L https://github.com/ssabro/hwpx-skill/archive/refs/heads/main.tar.gz | tar -xz
cd hwpx-skill-main

# Windows (PowerShell)
Invoke-WebRequest https://github.com/ssabro/hwpx-skill/archive/refs/heads/main.zip -OutFile hwpx-skill.zip
Expand-Archive hwpx-skill.zip -DestinationPath .
Set-Location hwpx-skill-main
```

#### 2) Python 의존성

```bash
pip install python-hwpx
# PEP 668 시스템 파이썬을 강제로 쓸 때만
pip install python-hwpx --break-system-packages
```

#### 3) 스킬을 Claude Code 로 연결

```bash
# macOS / Linux
cp -r . ~/.claude/skills/hwpx

# Windows (PowerShell)
robocopy . "$env:USERPROFILE\.claude\skills\hwpx" /E
```

#### 4) 스켈레톤 1 회 생성

```bash
python scripts/build_report_skeleton.py
# 결과: assets/report-skeleton.hwpx
```

스켈레톤은 `{{ORG_NAME}}`, `{{REPORT_TITLE}}`, `{{REPORT_DATE}}` …
와 같은 마커가 박힌 최소 구조의 HWPX 문서이다. 이 프로젝트 전용 마커
네이밍이며 다른 프로젝트의 플레이스홀더와 충돌하지 않는다.

## 빠른 사용 예

### 보고서 — 스켈레톤 기반

```python
import shutil
from pathlib import Path
from hwpx_toolkit import HwpxPackage

shutil.copy("assets/report-skeleton.hwpx", "report.hwpx")

with HwpxPackage.open("report.hwpx") as pkg:
    pkg.replace_all({
        "{{ORG_NAME}}":     "AI 정책국",
        "{{REPORT_TITLE}}": "2026 하반기 운영 계획",
        "{{REPORT_DATE}}":  "2026. 4. 21.",
        "{{DOC_SUBTITLE}}": "정책 방향 및 실행 계획",
    })
    pkg.replace_ordered("{{HEADING_L1}}", ["추진 배경", "현황", "개선"])
    pkg.normalize_namespaces()
    pkg.commit()
```

### 공문 — 빈 문서에서 새로 작성

```python
from hwpx.document import HwpxDocument
from hwpx_toolkit import normalize_namespaces_in_place

doc = HwpxDocument.new()
doc.add_paragraph("1. 관련: 교육정책과-1234(2026. 2. 1.)")
doc.add_paragraph("2. 2026 년도 정보화 교육을 다음과 같이 안내하오니 …")
doc.add_paragraph("  가. 일시: 2026. 3. 10.(화) 14:00 ∼ 16:00")
doc.add_paragraph("붙임  일정표 1부.  끝.")

doc.save("letter.hwpx")
normalize_namespaces_in_place("letter.hwpx")
```

## 트리거 예시

- "한글로 보고서 작성해줘"
- "이 hwpx 양식으로 채워줘"
- "공문/기안문 기안해줘"
- ".hwpx 파일 만들어줘"

상세 사용법은 `SKILL.md` 를 참고한다.

## 설계 특징

- **원자적 커밋** — 임시 파일에 쓴 뒤 `os.replace` 로 교체. 중단되어도
  원본이 손상되지 않는다.
- **XML 이스케이프 기본 ON** — 외부 입력을 치환 값으로 받아도 XML 인젝션
  위험이 없다.
- **ZIP bomb 방어** — 단일 엔트리 50 MB 상한.
- **Zip Slip 방어** — 로드 시 `..` 포함 엔트리 거부.
- **네임스페이스 정규화 일원화** — 라이브러리로서 `HwpxPackage` 안에도
  포함되고, 독립 CLI (`scripts/hwpx_ns_repair.py`) 로도 제공된다.
- **크로스 플랫폼** — `pathlib.Path`, `sys.executable` 사용. Windows /
  macOS / Linux 동일 코드로 동작.

## 라이선스

MIT. `LICENSE` 참고.
