# PDF -> MD 전처리 파이프라인 정리

## 전체 흐름
- CLI로 입력받은 PDF 경로를 열어 페이지 수와 문서 객체를 확보한다.【F:app/__main__.py†L34-L50】
- 문서를 전역적으로 스캔해 반복 등장하는 헤더·푸터 후보와 본문에서 가장 흔한 폰트 크기/색상을 추출한다.【F:app/__main__.py†L23-L45】【F:app/services/text_analizer.py†L51-L158】
- `iter_page_pipeline`으로 페이지를 순회하며 마크다운을 스트리밍 생성한다.【F:app/__main__.py†L46-L50】【F:app/core.py†L25-L105】
- 페이지 마크다운을 `<SEP>` 기준으로 분할해 섹션 단위 형태소 분석 → 동의어 정규화 → TF‑IDF 키워드 추출을 수행하고, 필요한 섹션에 `[[META]] keywords` 메타를 삽입해 최종 MD를 쓴다.【F:app/__main__.py†L52-L79】

## 페이지 파이프라인(`iter_page_pipeline`)
1. 페이지에서 텍스트 dict, 표, 드로잉을 읽고 이미지 블록을 제거해 순수 텍스트 spans만 남긴다.【F:app/core.py†L34-L43】【F:app/core.py†L156-L184】
2. 스팬들의 x좌표 빈도를 기반으로 세로 분할선(`y_rails`)을 계산한 뒤, 분할선을 따라 좌우 영역을 재귀적으로 분리해 2-up 페이지도 좌측 기준으로 정렬한다. 폭이 `MIN_RAIL_WIDTH` 미만인 레일은 버린다.【F:app/core.py†L47-L75】【F:app/configs/constants.py†L57-L58】【F:app/core.py†L107-L139】【F:app/services/text_box_clustering.py†L50-L74】
3. 본문 폰트 크기/페이지 크기에 기반해 사이드 캡션 영역 비율을 추정한다.【F:app/core.py†L77-L90】【F:app/services/caption_analizer.py†L6-L208】
4. 스팬을 분류해 태그를 달고, 허용된 타입(H1/H2/BODY/SEP)만 통과시킨다.【F:app/core.py†L85-L100】【F:app/services/text_analizer.py†L161-L262】【F:app/configs/constants.py†L47-L55】
5. 태그에 따라 `#`, `##`, `<SEP>`, `<META>` 등을 주입하며 마크다운 문자열을 만든다.【F:app/services/text_analizer.py†L286-L341】

## 스팬 분류 규칙 주요 포인트
- **페이지 번호 제거:** 하단 `bottom_ratio` 영역에서 페이지 번호 패턴(`PAGE_NUM_RE`)과 매칭될 때 `page-number`로 분류한다.【F:app/services/text_analizer.py†L11-L49】【F:app/configs/constants.py†L25-L27】
- **표 인접 텍스트:** `find_tables()` 결과에 맞춰 표 위 제목 띠·헤더·바디 행과 겹치면 `table-subject/header/row` 또는 단위 줄(`table-unit`)로 태깅한다.【F:app/services/text_analizer.py†L194-L199】【F:app/services/table_analizer.py†L72-L158】
- **제목:** 본문 폰트보다 충분히 크고 볼드(또는 길이 제한)에 맞으면 `h1`, 본문 크기와 비슷하지만 색상·볼드가 차별화되면 `h2`로 태깅한다.【F:app/services/text_analizer.py†L200-L213】
- **사이드 캡션:** 추정된 좌/우 캡션 영역과 길이/패턴 조건을 만족하면 `caption`으로 분류한다.【F:app/services/text_analizer.py†L222-L235】【F:app/services/caption_analizer.py†L212-L304】
- **기본 본문:** 위 조건이 모두 아닐 때 `body`로 남기며 이후 마크다운에서 헤더 뒤 첫 본문에 `<META>` 자리표시자를 삽입한다.【F:app/services/text_analizer.py†L236-L237】【F:app/services/text_analizer.py†L324-L333】

## 사이드 캡션 영역 추정 로직
- 본문 후보(폰트 크기·길이 조건)와 캡션 후보(작은 폰트·짧은 길이)를 분리한 뒤, 좌/우에 분포한 캡션 bbox로 기본 비율을 계산한다.【F:app/services/caption_analizer.py†L44-L149】
- 본문 여백을 넘지 않도록 캡션 폭을 제한하고, 중앙 정렬이거나 비대칭일 때 한쪽만 남기는 규칙을 적용한다.【F:app/services/caption_analizer.py†L150-L194】
- y분포를 이용해 상·하단 머리말/꼬리말 영역(`caption_y_ratio`)을 산출해 캡션 판별에서 제외한다.【F:app/services/caption_analizer.py†L195-L208】【F:app/services/caption_analizer.py†L262-L304】

## 형태소 및 키워드 후처리
- `<SEP>`로 구분된 섹션마다 Kiwi 형태소 분석 후 2-gram 명사를 추출하며, 최소 50개 토큰이 없으면 건너뛴다.【F:app/__main__.py†L56-L63】【F:app/services/text_analizer.py†L344-L370】
- 사전 정의된 동의어 맵(`SYN_MAP`)으로 명사를 정규화한다.【F:app/__main__.py†L64-L67】【F:app/configs/constants.py†L60-L66】
- TF‑IDF로 섹션별 상위 3개 키워드를 뽑아 `[[META]] keywords:` 메타라인으로 치환한다(본문이 짧고 키워드가 없으면 제거).【F:app/__main__.py†L69-L79】【F:app/services/text_analizer.py†L380-L408】

## 주요 상수
- 스팬 필터링 화이트리스트: `H1`, `H2`, `BODY`, `SEP`.【F:app/configs/constants.py†L47-L55】
- 페이지 분할 최소 레일 폭: `MIN_RAIL_WIDTH = 4`.【F:app/configs/constants.py†L57-L58】
- 동의어 정규화 맵: `농업협동조합→농협`, `농촌 농→농촌 농협`, `농 회→농협 회장`, `사 발간→60년사 발간`.【F:app/configs/constants.py†L60-L66】
