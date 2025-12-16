# ===
# name: [변환기] PDF > MD
# desc: PDF 데이터를 LLM 친화적으로 재해석
# release version: v0.2.0
# author: Lee
# regdate: 2025-12-15
# moddate: 2025-12-16
# ===

import os
import re
import copy
import glob
import logging
import fitz
import html2text
import asyncio
from app import *
from typing import *
from .services.text_analizer import markdown, classify_spans, filter_spans
from .services.text_box_clustering import cluster_by_x_rails, get_y_rails
from .services.caption_analizer import detect_side_caption_zones


@timeit_iter
def iter_page_pipeline(doc: fitz.Document, _: Dict, body_styles: Dict[str, float]):
    """페이지 단위 추출 제너레이터 (PDF -> MD)
    Args:
        doc (fitz.Document): 문서 객체
    Returns:
        Tuple[int, str]: page_idx, markdown_text
    """
    # 페이지 단위 데이터 스트리밍을 시작한다
    for page_idx in range(doc.page_count):
        page = doc.load_page(page_idx)
        dicts = page.get_text("dict")
        table_object = page.find_tables()
        drawings = page.get_drawings()

        # 이미지 블록은 제외한다
        blocks = _filter_img_blocks(dicts["blocks"])
        spans = _get_spans(blocks)

        page_w = page.rect.width
        page_h = page.rect.height

        # 세로 절개 기준선 목록을 얻는다
        y_rails: List[float] = get_y_rails(spans, padding=1)

        arranged_spans: List[List[Dict]] = []
        target_spans = spans

        for i, rail in enumerate(y_rails):
            # 절개선 기준으로 "오른쪽 영역"을 재귀적으로 절개하여 "왼쪽 영역"의 spans를 모은다
            left_spans, right_spans = _classify_spans_by_splited_page(
                target_spans, page_w, rail
            )
            # 너무 작은 간격의 레일의 spans 날린다
            if (
                i > 0
                and i < len(y_rails) - 1
                and y_rails[i + 1] - rail < MIN_RAIL_WIDTH
            ):
                left_spans = []

            if left_spans:
                # 왼쪽 영역 spans를 누적 -> 왼쪽 영역부터 순서대로 y 정렬되는 효과
                arranged_spans += left_spans

            # 다음 페이지 분할을 위해 오른쪽 spans를 타겟으로 세팅한다
            target_spans = right_spans

        # 마지막 페이지도 모은다
        arranged_spans += target_spans
        target_spans = []

        opts1 = {
            "body_font_size": body_styles["font_size"],
            "page_w": page_w,
            "page_h": page_h,
        }
        # detect side caption zones
        caption_zones = detect_side_caption_zones(arranged_spans, **opts1)

        opts2 = {
            "body_font_size": body_styles["font_size"],
            "body_font_color": body_styles["font_color"],
            "page_h": page_h,
            "page_w": page_w,
            "tables": table_object.tables,
            "caption_zones": caption_zones,
        }
        # [태깅] span 단위로 텍스트 분류 태깅
        _spans = classify_spans(arranged_spans, **opts2)

        # [필터링] 분류된 텍스트 태그로 라인 필터링
        _spans = filter_spans(_spans, WHITELIST)

        # 스팬을 까서 마크다운 생성한다
        md = markdown(_spans)
        arranged_spans = []

        # 스트림 출력한다
        yield page_idx, md


def _classify_spans_by_splited_page(spans, page_w, mid_x):
    """분할된 페이지에서 spans를 분류한다 (분할선 기준 왼쪽 spans 반환)
    Args:
        spans (List[Dict]): source spans
        page_w (float): page width
        mid_x (float): coordinate of split rail
    Returns:
        List[Dict]: target spans
    """
    left_spans = []
    right_spans = []

    for s in spans:
        bbox = s.get("bbox")
        if bbox and len(bbox) >= 4:
            x0, y0, x1, y1 = bbox[0], bbox[1], bbox[2], bbox[3]

            # 2-up-layout: 우측 페이지의 좌표를 좌측 페이지 기준으로 변환
            if x0 > page_w:
                x0 = x0 - page_w
                x1 = x1 - page_w

            center_x = (x0 + x1) / 2.0
        else:
            # fallback: treat as left if no bbox
            center_x = 0

        if center_x < mid_x:
            left_spans.append(s)
        else:
            right_spans.append(s)

    return left_spans, right_spans


def _sort_spans_by_layout(spans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Y좌표와 X좌표 기준으로 span들을 레이아웃 순서대로 정렬

    Args:
        spans (List[Dict[str, Any]]): span 리스트

    Returns:
        List[Dict[str, Any]]: 정렬된 span 리스트
    """
    # bbox: [x0, y0, x1, y1]
    return sorted(spans, key=lambda s: (s["bbox"][1], s["bbox"][0], s["size"]))


def _filter_img_blocks(blocks):
    """
    filter image blocks
    """
    results = []
    for b in blocks:
        if b["type"] == TEXT:
            results.append(b)
    return results


def _get_spans(blocks):
    """블록을 넣어 스팬을 얻는다
    Args:
        blocks (List): 블록
    Returns:
        List: 스팬
    """
    spans = []
    lines = [l for b in blocks for l in b["lines"]]

    if len(lines) == 0:
        return []

    spans = []
    for line in lines:
        spans += [span for span in line["spans"]]

    return spans
