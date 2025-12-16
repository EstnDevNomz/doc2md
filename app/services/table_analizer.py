from __future__ import annotations
import re
from typing import Any, Dict, Iterable, Optional, Tuple, List
from app import *


def _is_unit_line(text: str) -> bool:
    return bool(UNIT_PATTERN.match(text))


# ---------- bbox 유틸 ---------- #
def _bbox_area(bbox: BBOX) -> float:
    x0, y0, x1, y1 = bbox
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def _bbox_intersection(a: BBOX, b: BBOX) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b

    ix0 = max(ax0, bx0)
    iy0 = max(ay0, by0)
    ix1 = min(ax1, bx1)
    iy1 = min(ay1, by1)

    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    return (ix1 - ix0) * (iy1 - iy0)


def _overlap_ratio(span_bbox: BBOX, region_bbox: BBOX) -> float:
    """
    span_bbox와 region_bbox의 겹치는 비율(0~1).
    기준: span 영역 중 몇 %가 region 안에 들어가는가.
    """
    inter = _bbox_intersection(span_bbox, region_bbox)
    if inter <= 0.0:
        return 0.0

    area = _bbox_area(span_bbox)
    if area <= 0.0:
        return 0.0

    return inter / area


def _best_match_row_index(
    span_bbox: BBOX,
    row_bboxes: List[BBOX],
    min_overlap: float,
) -> Optional[int]:
    """
    span_bbox가 어떤 row bbox랑 가장 많이 겹치는지 찾고,
    overlap 비율이 min_overlap 이상이면 그 row index 반환.
    없으면 None.
    """
    best_idx: Optional[int] = None
    best_score = 0.0

    for idx, row_bbox in enumerate(row_bboxes):
        score = _overlap_ratio(span_bbox, row_bbox)
        if score >= min_overlap and score > best_score:
            best_score = score
            best_idx = idx

    return best_idx


# ---------- 메인: Table 객체 기반 분류 ---------- #


def classify_span_with_tables(
    span: Dict[str, Any],
    tables: Iterable[Any],
    *,
    # 표 제목 영역은 "표 전체 bbox 바로 위의 띠"로 가정
    # ratio 기준: 표 높이 * subject_band_margin_top 만큼 위쪽 영역을 제목 후보 영역으로 삼음
    subject_band_margin_top: float = 10,
    min_overlap_subject: float = 0.4,
    min_overlap_header: float = 0.4,
    min_overlap_body: float = 0.5,
    page_w: float | None = None,
) -> Optional[str]:
    """
    PyMuPDF page.find_tables()가 리턴한 table 객체들을 기반으로
    span이 어느 영역(제목/헤더/바디 행)에 속하는지 판별.

    tables: page.find_tables().tables

    Return:
      - TABLE_SUBJECT
      - TABLE_HEADER
      - TABLE_BODY_ROW_{n}
      - 해당 없음: None
    """
    sx0, sy0, sx1, sy1 = span["bbox"]

    if sx0 > page_w:
        sx0 = sx0 - page_w
        sx1 = sx1 - page_w

    span_bbox: BBOX = (sx0, sy0, sx1, sy1)

    for table in tables:
        # table.bbox: 표 전체 영역
        tx0, ty0, tx1, ty1 = table.bbox
        table_bbox: BBOX = (tx0, ty0, tx1, ty1)

        # 1) 표 제목 영역: 표 바로 위 subject_band_margin_top 만큼의 수평 띠
        #    e.g. 표 높이의 10 만큼 바로 위 영역을 제목 후보로 본다.
        table_height = max(1.0, ty1 - ty0)
        subject_height = table_height + subject_band_margin_top

        subject_bbox: BBOX = (
            tx0,
            max(0.0, ty0 - subject_height),
            tx1,
            ty0,
        )

        subject_overlap = _overlap_ratio(span_bbox, subject_bbox)
        if subject_overlap >= min_overlap_subject:
            text = span.get("text", "").strip()

            # (1) 단위 줄이면 별도 태깅
            if _is_unit_line(text):
                return TABLE_UNIT

            # (2) 그 외는 제목으로 태깅
            return TABLE_SUBJECT

        # 2) 헤더 영역: table.header.bbox 사용
        header_bbox: Optional[BBOX] = None
        if getattr(table, "header", None) is not None:
            hx0, hy0, hx1, hy1 = table.header.bbox
            header_bbox = (hx0, hy0, hx1, hy1)

        if header_bbox is not None:
            header_overlap = _overlap_ratio(span_bbox, header_bbox)
            if header_overlap >= min_overlap_header:
                return TABLE_HEADER

        # 3) 바디 행 영역: table.rows[i].bbox 사용
        row_bboxes: List[BBOX] = []
        for row in getattr(table, "rows", []):
            rx0, ry0, rx1, ry1 = row.bbox
            row_bboxes.append((rx0, ry0, rx1, ry1))

        if row_bboxes:
            row_idx = _best_match_row_index(
                span_bbox,
                row_bboxes,
                min_overlap=min_overlap_body,
            )
            if row_idx is not None:
                return f"table-row-{row_idx + 1}"

    return None
