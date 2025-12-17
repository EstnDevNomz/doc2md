import fitz
import re
from typing import List, Dict, Tuple, Optional

BULLET_RE = re.compile(r"^\s*[•·∙◦▪■]\s*")


def _to_rect(bbox) -> fitz.Rect:
    return bbox if isinstance(bbox, fitz.Rect) else fitz.Rect(bbox)


def _text(sp) -> str:
    return (sp.get("text") or "").strip()


def _size(sp) -> float:
    try:
        return float(sp.get("size", 0.0))
    except Exception:
        return 0.0


def _x0(sp) -> float:
    return _to_rect(sp["bbox"]).x0


def _y0(sp) -> float:
    return _to_rect(sp["bbox"]).y0


def _y1(sp) -> float:
    return _to_rect(sp["bbox"]).y1


def _x_overlap(a: fitz.Rect, b: fitz.Rect) -> float:
    inter = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
    denom = min(a.width, b.width) if min(a.width, b.width) > 0 else 1.0
    return inter / denom


def _is_title_box(
    dr: Dict, page: fitz.Page, max_h_ratio: float = 0.18, min_w_ratio: float = 0.12
) -> bool:
    r = dr.get("rect")
    if not isinstance(r, fitz.Rect):
        return False

    page_w, page_h = page.rect.width, page.rect.height

    # 너무 큰 영역(본문 전체 박스) 제외
    if r.height > page_h * max_h_ratio:
        return False
    if r.width < page_w * min_w_ratio:
        return False

    # "색 있는 상단 바"일 확률: fill 또는 stroke가 존재
    if dr.get("fill") is None and dr.get("color") is None:
        return False

    return True


def _pick_title_from_box(spans: List[Dict], box: fitz.Rect) -> str:
    pad = 2.0
    b_in = fitz.Rect(box.x0 - pad, box.y0 - pad, box.x1 + pad, box.y1 + pad)

    # (A) 박스 "내부" contains
    cands = [sp for sp in spans if _text(sp) and b_in.contains(_to_rect(sp["bbox"]))]

    # (B) 내부에 없으면, "겹치기"로 완화 (bbox가 살짝 삐져나오는 케이스 방어)
    if not cands:
        cands = []
        for sp in spans:
            t = _text(sp)
            if not t:
                continue
            r = _to_rect(sp["bbox"])
            inter = b_in & r
            if not inter.is_empty and inter.get_area() >= r.get_area() * 0.3:
                cands.append(sp)

    # (C) 그래도 없으면, 박스 바로 아래 얕은 영역(제목이 아래에 있는 케이스)
    if not cands:
        # 제목은 보통 박스 아래로 1~2줄 정도에 있음
        below_h = max(12.0, box.height * 1.2)
        b_below = fitz.Rect(box.x0 - 5, box.y1, box.x1 + 5, box.y1 + below_h)

        cands = [
            sp for sp in spans if _text(sp) and b_below.intersects(_to_rect(sp["bbox"]))
        ]

    if not cands:
        return ""

    # 제목 후보: 글씨 크기 > 짧은 길이 > 위쪽
    cands.sort(key=lambda sp: (-_size(sp), len(_text(sp)), _y0(sp)))
    return _text(cands[0])


def _collect_bullets_below(
    spans: List[Dict],
    col_rect: fitz.Rect,
    y_start: float,
    y_end: float,
    *,
    bullet_only: bool = True,
) -> List[str]:
    items = []
    for sp in spans:
        t = _text(sp)
        if not t:
            continue
        r = _to_rect(sp["bbox"])

        if r.y0 < y_start or r.y1 > y_end:
            continue

        # 같은 컬럼(가로 겹침)
        if _x_overlap(col_rect, r) < 0.3:
            continue

        if bullet_only:
            if not BULLET_RE.match(t):
                continue
            t = BULLET_RE.sub("", t).strip()

        if t:
            items.append((r.y0, t))

    # 위에서 아래로 정렬 + 중복 제거(같은 줄이 쪼개져 들어오는 경우 방어)
    items.sort(key=lambda x: x[0])
    dedup = []
    seen = set()
    for _, t in items:
        key = t.replace(" ", "")
        if key in seen:
            continue
        seen.add(key)
        dedup.append(t)
    return dedup


def _collect_lines_below(
    spans: List[Dict],
    col_rect: fitz.Rect,
    y_start: float,
    y_end: float,
    *,
    min_x_overlap: float = 0.3,
) -> List[str]:
    items = []
    for sp in spans:
        t = _text(sp)
        if not t:
            continue
        r = _to_rect(sp["bbox"])

        if r.y0 < y_start or r.y1 > y_end:
            continue

        if _x_overlap(col_rect, r) < min_x_overlap:
            continue

        items.append((r.y0, r.x0, t))

    # 위->아래, 좌->우
    items.sort(key=lambda x: (x[0], x[1]))

    # 같은 라인(y가 비슷한 텍스트) 합치기
    merged = []
    cur_y = None
    buf = []
    for y, x, t in items:
        if cur_y is None:
            cur_y = y
            buf = [t]
            continue

        # 같은 줄로 간주(2~4px 정도 튜닝)
        if abs(y - cur_y) <= 3.0:
            buf.append(t)
        else:
            line = " ".join(buf).strip()
            if line:
                merged.append(line)
            cur_y = y
            buf = [t]

    if buf:
        line = " ".join(buf).strip()
        if line:
            merged.append(line)

    # 중복 제거(특히 줄이 쪼개져 들어오는 케이스)
    out, seen = [], set()
    for s in merged:
        key = s.replace(" ", "")
        if key in seen:
            continue
        seen.add(key)
        out.append(s)

    return out


def _normalize_spans_bbox_to_page(spans: List[Dict], page: fitz.Page) -> List[Dict]:
    """
    spans bbox 좌표가 page 좌표(포인트)인지, 렌더 픽셀 좌표인지 자동 감지해서
    픽셀 좌표면 page 좌표로 스케일 다운.
    """
    if not spans:
        return spans

    page_w, page_h = page.rect.width, page.rect.height

    # spans bbox의 최대 좌표
    max_x = 0.0
    max_y = 0.0
    for sp in spans:
        r = _to_rect(sp["bbox"])
        max_x = max(max_x, r.x1)
        max_y = max(max_y, r.y1)

    # page보다 "의미 있게" 크면(=픽셀 좌표일 확률 높음) 스케일로 판단
    # 예: page_w~595pt(A4)인데 spans max_x가 3000이면 5배 => 360~400dpi 렌더
    sx = max_x / page_w if page_w else 1.0
    sy = max_y / page_h if page_h else 1.0

    # 스케일이 1에 가깝다면 이미 page 좌표
    if sx < 1.5 and sy < 1.5:
        return spans

    # 너무 과격한 값은 제외(이상치 방어)
    if sx > 50 or sy > 50:
        return spans

    # 보통 sx, sy는 거의 같음. 그래도 안전하게 각각 적용
    out = []
    for sp in spans:
        r = _to_rect(sp["bbox"])
        sp2 = dict(sp)
        sp2["bbox"] = (r.x0 / sx, r.y0 / sy, r.x1 / sx, r.y1 / sy)
        out.append(sp2)

    return out


def solt_spans_with_drawing_boxes(
    page: fitz.Page,
    spans: List[Dict],
    *,
    max_titlebox_h_ratio: float = 0.18,
) -> str:
    if not spans:
        return ""

    # ✅ 좌표계 정규화: 이거 없으면 대부분 케이스에서 아래 내용이 0개로 나옴
    spans = _normalize_spans_bbox_to_page(spans, page)

    drawings = page.get_drawings()

    # 1) 제목 박스 후보 추출
    title_boxes = []
    for dr in drawings:
        if _is_title_box(dr, page, max_h_ratio=max_titlebox_h_ratio):
            title_boxes.append(dr["rect"])

    # 2) 중복 제거 + 정렬(위->아래, 좌->우)
    title_boxes = sorted(title_boxes, key=lambda r: (r.y0, r.x0))
    uniq = []
    for r in title_boxes:
        dup = False
        for rr in uniq:
            if (
                abs(r.x0 - rr.x0) < 2
                and abs(r.y0 - rr.y0) < 2
                and abs(r.x1 - rr.x1) < 2
                and abs(r.y1 - rr.y1) < 2
            ):
                dup = True
                break
        if not dup:
            uniq.append(r)
    title_boxes = uniq

    # 3) 각 박스별 섹션 구성
    sections = []
    for i, tb in enumerate(title_boxes):
        title = _pick_title_from_box(spans, tb)

        # 컬럼 영역: 제목 박스와 동일한 x-range를 기본으로 하되, 약간 확장
        col = fitz.Rect(tb.x0 - 5, tb.y0, tb.x1 + 5, page.rect.y1)

        y_start = tb.y1 + 2
        # 다음 제목 박스가 같은 컬럼이면 그 위까지, 아니면 페이지 끝까지
        y_end = page.rect.y1
        for j in range(i + 1, len(title_boxes)):
            nb = title_boxes[j]
            if _x_overlap(col, nb) >= 0.3:
                y_end = nb.y0 - 2
                break

        # ✅ 조직도/설명형 박스는 bullet이 아니라 '문단'임
        body_lines = _collect_lines_below(
            spans, col, y_start, y_end
        )  # 내가 이전에 준 함수 그대로

        bullets = _collect_bullets_below(spans, col, y_start, y_end, bullet_only=True)

        # ✅ 본문이 없으면 섹션 의미 없음
        if not body_lines and not bullets:
            continue

        sections.append((tb, title, body_lines, bullets))

        return spans
