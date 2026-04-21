# HWPX 포맷 내부 구조 메모

HWPX(.hwpx)는 ODF·OOXML 과 동일하게 **ZIP 컨테이너 안의 XML 문서 집합**이다.
표준은 KS X 6101(OWPML, Open Word-Processor Markup Language)이며,
한컴오피스 2014 이후 버전에서 지원된다. 본 문서는 이 프로젝트의 스크립트
(특히 `scripts/hwpx_toolkit.py`)가 어떤 구조를 가정하고 동작하는지를
간단히 정리한 참고 노트이다.

## 1. ZIP 엔트리 레이아웃

```
document.hwpx                         (ZIP)
├── mimetype                          "application/hwp+zip" (단일 줄, 압축 금지 권장)
├── version.xml                       HWPML 버전 명시
├── settings.xml                      열람/편집 설정
├── META-INF/
│   ├── container.xml                 루트 파일(= Contents/content.hpf) 등록
│   ├── container.rdf                 RDF 메타
│   └── manifest.xml                  파트/MIME 매니페스트
├── Preview/
│   ├── PrvImage.png                  표지 썸네일
│   └── PrvText.txt                   일부 텍스트 요약
└── Contents/
    ├── content.hpf                   파트 목록, 바이너리 자원 선언(OPF)
    ├── header.xml                    글꼴·글자속성·문단속성·테두리·글머리
    └── section*.xml                  section0.xml, section1.xml ... 본문
```

`Contents/` 아래의 XML 파트가 **편집 대상**이다. 나머지는 보조 메타데이터이므로
이 프로젝트의 툴킷은 Contents 하위만 변형한다(`_is_contents_xml`).

## 2. 네임스페이스

OWPML 2011 스펙에서 정의한 URI 와, 한컴 Viewer 가 매칭을 전제하는
**canonical prefix** 는 다음과 같다.

| 용도         | URI                                                  | prefix |
|--------------|------------------------------------------------------|--------|
| head 요소    | http://www.hancom.co.kr/hwpml/2011/head              | `hh`   |
| core 타입    | http://www.hancom.co.kr/hwpml/2011/core              | `hc`   |
| 문단 노드    | http://www.hancom.co.kr/hwpml/2011/paragraph         | `hp`   |
| 섹션 루트    | http://www.hancom.co.kr/hwpml/2011/section           | `hs`   |
| app 확장     | http://www.hancom.co.kr/hwpml/2011/app               | `ha`   |
| 2016 확장    | http://www.hancom.co.kr/hwpml/2016/paragraph         | `hp10` |

`xml.etree.ElementTree` 를 포함한 범용 XML 라이브러리는 출력 시 `ns0`,
`ns1` 같은 자동 prefix 를 쓴다. 이 상태 그대로 저장한 문서를 Hangul Viewer
(특히 macOS 빌드)에서 열면 **본문이 렌더링되지 않고 빈 페이지로 표시**되는
경우가 자주 보고된다. 따라서 모든 저장 흐름의 마지막 단계에서
`normalize_namespaces_in_place(path)` 를 호출해 canonical prefix 로 정규화한다.

## 3. 단위(HWPUNIT)

HWPX 내부 길이 단위는 **HWPUNIT**. 환산식은 다음 한 줄로 기억한다.

```
1 inch = 7200 HWPUNIT
1 mm   ≒ 283.465 HWPUNIT
```

A4 와 흔히 쓰는 여백 값의 정수 근삿값:

| 의미           | mm   | HWPUNIT |
|----------------|------|---------|
| A4 너비        | 210  | 59528   |
| A4 높이        | 297  | 84186   |
| 여백 10 mm     | 10   | 2835    |
| 여백 15 mm     | 15   | 4252    |
| 여백 20 mm     | 20   | 5669    |

글자 크기(`hh:charPr@height`) 는 1/100 pt 단위. 예: `height="1600"` ⇒ 16 pt.

## 4. `header.xml` 에서 자주 보는 요소

### 4-1. 글꼴 목록

```xml
<hh:fontface lang="HANGUL" fontCnt="…">
  <hh:font id="0" face="함초롬돋움" type="TTF" isEmbedded="0"/>
  <hh:font id="1" face="함초롬바탕" type="TTF" isEmbedded="0"/>
  <!-- ... -->
</hh:fontface>
```

글자속성(`charPr`) 의 `fontRef` 가 언어별 fontface 의 `id` 를 참조한다.

### 4-2. 글자 속성

```xml
<hh:charPr id="5" height="1600" textColor="#000000" italic="0">
  <hh:fontRef hangul="3" latin="0" hanja="3" .../>
  <hh:bold .../>
</hh:charPr>
```

### 4-3. 문단 속성

```xml
<hh:paraPr id="28">
  <hh:align horizontal="CENTER" vertical="BASELINE"/>
  <hh:margin>
    <hc:intent value="-2606" unit="HWPUNIT"/>
  </hh:margin>
  <hh:lineSpacing type="PERCENT" value="160" unit="HWPUNIT"/>
  <hp:spacing before="0" after="0" .../>
</hh:paraPr>
```

- `horizontal`: `LEFT` / `CENTER` / `RIGHT` / `JUSTIFY`
- `intent.value` 음수 = 내어쓰기
- `lineSpacing.value` 는 PERCENT 기준 정수

### 4-4. 테두리·채움

```xml
<hh:borderFill id="9">
  <hh:leftBorder  type="SOLID" width="0.12 mm" color="#006699"/>
  <hh:rightBorder type="SOLID" width="0.12 mm" color="#006699"/>
  <hh:fillBrush>
    <hh:windowBrush faceColor="#193AAA" hatchColor="#000000" hatchStyle="NONE"/>
  </hh:fillBrush>
</hh:borderFill>
```

## 5. `section*.xml` 에서 자주 보는 요소

### 5-1. 용지/여백

```xml
<hp:pagePr landscape="WIDELY" width="59528" height="84188"
           gutterType="LEFT_ONLY">
  <hp:margin header="4251" footer="4251" gutter="0"
             left="5669" right="5669" top="5669" bottom="2835"/>
</hp:pagePr>
```

### 5-2. 문단 / 런

```xml
<hp:p id="…" paraPrIDRef="28" styleIDRef="0" pageBreak="0">
  <hp:run charPrIDRef="5">
    <hp:t>본문 텍스트</hp:t>
  </hp:run>
</hp:p>
```

`pageBreak="1"` 이면 이 문단 앞에서 페이지가 나뉜다.

### 5-3. 표

```xml
<hp:tbl rowCnt="1" colCnt="3" borderFillIDRef="5">
  <hp:sz width="47688" widthRelTo="ABSOLUTE" height="2832" heightRelTo="ABSOLUTE"/>
  <hp:pos treatAsChar="1" horzAlign="LEFT" vertAlign="TOP"/>
  <hp:tr>
    <hp:tc borderFillIDRef="9">
      <hp:subList vertAlign="CENTER">
        <hp:p paraPrIDRef="3">
          <hp:run charPrIDRef="24"><hp:t>Ⅰ</hp:t></hp:run>
        </hp:p>
      </hp:subList>
      <hp:cellAddr colAddr="0" rowAddr="0"/>
      <hp:cellSz width="3327" height="2832"/>
    </hp:tc>
    <!-- 나머지 셀 -->
  </hp:tr>
</hp:tbl>
```

### 5-4. 이미지 참조 (3단계)

1. `Contents/content.hpf` 의 manifest 에 등록

   ```xml
   <opf:item id="image1" href="BinData/image1.png"
             media-type="image/png" isEmbeded="1"/>
   ```
2. `BinData/image1.png` 엔트리 존재
3. `section*.xml` 에서 `hc:img` 로 참조

   ```xml
   <hc:img binaryItemIDRef="image1" bright="0" contrast="0"
           effect="REAL_PIC" alpha="0"/>
   ```

## 6. 툴킷이 전제하는 것

`scripts/hwpx_toolkit.py` 의 `HwpxPackage` 는 이 포맷에 대해 다음과 같은
가정을 한다. 이 가정이 깨지는 문서는 별도 처리가 필요하다.

- 파일은 표준 ZIP, 트래버설 경로(`..`) 나 절대경로 엔트리가 없다.
- 단일 엔트리 크기는 50 MB 이하이다 (`HwpxConfig.max_entry_bytes`).
- 텍스트 치환 대상은 `Contents/` 하위의 `.xml` 파트이다.
- 치환 값은 기본적으로 XML 이스케이프된다 (`escape_values=True`).
  플레이스홀더 값 자체에 XML 마크업을 넣어야 한다면 이 옵션을 끈다.
- 네임스페이스 정규화는 `ns0`, `ns1` 과 같이 `ns` + 숫자 패턴의
  자동 prefix 만 다시 매핑한다. 이미 canonical prefix 를 쓰는 문서는
  통과된다.

## 7. 페이지 설정을 코드로 바꾸는 예시

```python
import xml.etree.ElementTree as ET
from hwpx.document import HwpxDocument

from hwpx_toolkit import normalize_namespaces_in_place

doc = HwpxDocument.open("in.hwpx")
section = doc.sections[0]
ns = {"hp": "http://www.hancom.co.kr/hwpml/2011/paragraph"}

pagePr = section.element.find(".//hp:pagePr", ns)
if pagePr is not None:
    pagePr.set("width",  "59528")   # A4 너비
    pagePr.set("height", "84186")   # A4 높이
    margin = pagePr.find("hp:margin", ns)
    if margin is not None:
        margin.set("left",   "5669")
        margin.set("right",  "5669")
        margin.set("top",    "4252")
        margin.set("bottom", "4252")

doc.save("out.hwpx")
normalize_namespaces_in_place("out.hwpx")
```

## 8. 호환성 주의점

- **HWPX 만** 다룬다. 레거시 `.hwp`(바이너리) 는 범위 밖이다.
- 한글 뷰어가 아닌 서드파티 툴(LibreOffice 등)의 HWPX 렌더링은
  제한적이다. 배포 시 PDF 동시 제공을 고려한다.
- 글꼴은 임베딩하지 않는 한 열람 환경에 의존한다. 생성 측에서 기본
  글꼴을 지정하더라도 최종 표현은 사용자의 시스템 글꼴에 좌우될 수
  있다.
