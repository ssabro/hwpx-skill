# hwpx-skill

[Canine89/gonggong_hwpxskills](https://github.com/Canine89/gonggong_hwpxskills)를 기반으로 **크로스 플랫폼 호환성, 문서 일관성, 보안 강화** 작업을 수행한 포크입니다.

## 개요

한글(한컴오피스)의 HWPX 문서를 Claude Code 스킬로 생성, 읽기, 편집, 템플릿 치환하는 도구입니다. `python-hwpx` 라이브러리와 ZIP-level XML 치환 방식을 사용합니다.

## 프로젝트 구조

```
hwpx-skill/
├── SKILL.md                         # 스킬 본문 (Claude Code가 읽는 메인 문서)
├── assets/
│   └── report-template.hwpx         # 보고서 기본 양식 템플릿
├── scripts/
│   └── fix_namespaces.py            # HWPX 네임스페이스 후처리 유틸리티
├── references/
│   ├── report-style.md              # 보고서 양식 상세 가이드
│   ├── official-doc-style.md        # 공문서(기안문) 양식 가이드
│   └── xml-internals.md             # HWPX 내부 XML 구조 참조
└── evals/
    └── evals.json                   # 스킬 평가 테스트 케이스
```

## 원본 대비 변경 사항

### 1. 크로스 플랫폼 호환성

원본은 macOS/Linux(특히 Claude.ai Projects 환경)에서만 테스트되었습니다. Windows, Linux, macOS 모두에서 동작하도록 수정했습니다.

| 항목 | 원본 | 수정 후 |
|------|------|---------|
| 파일 경로 | `/mnt/skills/user/hwpx/`, `/home/claude/` 등 하드코딩 | `os.path.join()` + 상대 경로 |
| Python 실행 | `subprocess.run(["python", ...])` | `subprocess.run([sys.executable, ...])` |
| pip 설치 | `pip install python-hwpx --break-system-packages` | venv 권장 안내 추가, PEP 668 환경 별도 안내 |

**수정 파일**: `SKILL.md`

### 2. 문서 일관성 수정

파일 간 모순되는 안내를 통일했습니다.

| 항목 | 원본 | 수정 후 |
|------|------|---------|
| `fix_namespaces.py` docstring | `exec(open(...).read())` 방식 안내 | `from fix_namespaces import` 방식으로 변경 |
| `report-style.md` 예제 코드 | 존재하지 않는 `hwpx_replace` 모듈 import, `HwpxDocument.open()` 사용 | ZIP-level 치환(`zip_replace`)으로 통일 |
| `SKILL.md` 주의사항 | `exec()` 사용 금지만 안내 | 직접 import 방식과 `sys.executable` 방식 모두 안내 |

**수정 파일**: `fix_namespaces.py`, `references/report-style.md`, `SKILL.md`

### 3. 보안 강화

ZIP 파일을 직접 다루는 코드에 보안 방어를 추가했습니다.

| 취약점 | 심각도 | 대응 |
|--------|--------|------|
| 예측 가능한 임시파일 경로 (TOCTOU 경쟁조건) | HIGH | `tempfile.mkstemp()` 사용 + 실패 시 cleanup |
| XML 인젝션 (치환 값에 `<>&` 미이스케이핑) | MEDIUM | `xml.sax.saxutils.escape()` 기본 적용 (`escape_xml=True`) |
| ZIP bomb (메모리 소진 공격) | MEDIUM | ZIP 엔트리당 50MB 크기 제한 검증 |
| Zip Slip (경로 순회) | LOW | ZIP 엔트리 파일명의 `..`, 절대 경로 검증 |
| 비원자적 파일 교체 | LOW | `os.remove()` + `os.rename()` → `os.replace()` 원자적 교체 |

**수정 파일**: `scripts/fix_namespaces.py`, `SKILL.md`

## 설치

```bash
# 1. python-hwpx 설치
pip install python-hwpx

# 2. 이 저장소를 Claude Code 스킬 디렉토리에 복사
# macOS/Linux
cp -r hwpx-skill ~/.claude/skills/hwpxskill

# Windows
xcopy /E /I hwpx-skill %USERPROFILE%\.claude\skills\hwpxskill
```

## 원본 저장소

- **원본**: [Canine89/gonggong_hwpxskills](https://github.com/Canine89/gonggong_hwpxskills)
- **라이선스**: 원본 저장소의 라이선스를 따릅니다.
