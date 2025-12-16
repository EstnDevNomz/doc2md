# ===
# name: [변환기] PDF > MD
# desc: PDF 데이터를 LLM 친화적으로 재해석
# release version: v0.1.0
# author: Lee
# regdate: 2025-12-04
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
from .services.text_analizer import *


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
    spans = []
    lines = [l for b in blocks for l in b["lines"]]

    if len(lines) == 0:
        return []

    spans = []
    for line in lines:
        spans += [span for span in line["spans"]]

    return spans


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


@atimeit
async def get_pdf_ast_from(file_path: str):
    ast = fitz.open(file_path)
    return ast.page_count, ast


@atimeit
async def analize_pdf(doc: fitz.Document):
    tasks = [
        collect_header_footer_candidates(doc),  # TODO: 헤더 푸터 메타로 활용 예정
        get_body_font_style(doc),  # 본문 폰트 크기
    ]
    results = asyncio.gather(*tasks)

    return await results


def _split_page_by_width(spans, page_w, mid_x):
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


@timeit_iter
def iter_page_pipeline2(lines):
    return doc


@timeit_iter
def iter_page_pipeline(doc: fitz.Document, _, body_styles: Dict[str, float]):
    # 페이지 단위 데이터 스트리밍을 시작한다
    for page_idx in range(doc.page_count):
        page = doc.load_page(page_idx)
        dicts = page.get_text("dict")
        table_object = page.find_tables()
        drawings = page.get_drawings()

        blocks = _filter_img_blocks(dicts["blocks"])
        spans = _get_spans(blocks)

        solted_spans = _sort_spans_by_layout(spans)

        page_w = page.rect.width
        page_h = page.rect.height

        # 2-up-layout check
        # - If the page is landscape (wider than tall), split it vertically into
        # - two halves (left then right) and treat each half as its own page
        # - so the reading order is preserved for two-column/landscape scans.
        if page_w > page_h:
            mid_x = page_w / 2.0

            # Split left and right spans by page width as if it's a pge with 2-up-layout
            left_spans, right_spans = _split_page_by_width(solted_spans, page_w, mid_x)

            # Normalize and append left then right (skip empty halves)
            for sub_spans in (left_spans, right_spans):
                if not sub_spans:
                    continue

                # detect side caption zones
                caption_zones = detect_side_caption_zones(
                    sub_spans,
                    body_font_size=body_styles["font_size"],
                    page_w=page_w / 2.0,
                    page_h=page_h,
                )

                opts2 = {
                    "body_font_size": body_styles["font_size"],
                    "body_font_color": body_styles["font_color"],
                    "page_h": page_h,
                    "page_w": page_w / 2.0,
                    "tables": table_object.tables,
                    "caption_zones": caption_zones,
                }

                # 라인 단위로 텍스트 분류 태깅
                _spans = classify_spans(sub_spans, **opts2)

                # 렌더링 박스 안에 텍스트가 있는경우 제목과 내용 추출
                _spans = solt_spans_with_drawing_boxes(page, _spans)

                # 분류된 텍스트 태그로 라인 필터링
                _spans = filter_spans(_spans, WHITELIST)

                if md_from_boxes:
                    yield page_idx, md_from_boxes
                else:
                    # 라인을 모아서 페이지 단위로 취합
                    md = markdown(_spans)

                    # pages.append(page_data)
                    yield page_idx, md

        else:
            opts1 = {
                "body_font_size": body_styles["font_size"],
                "page_w": page_w,
                "page_h": page_h,
            }
            # detect side caption zones
            caption_zones = detect_side_caption_zones(solted_spans, **opts1)

            opts2 = {
                "body_font_size": body_styles["font_size"],
                "body_font_color": body_styles["font_color"],
                "page_h": page_h,
                "page_w": page_w,
                "tables": table_object.tables,
                "caption_zones": caption_zones,
            }
            # 라인 단위로 텍스트 분류 태깅
            _spans = classify_spans(solted_spans, **opts2)

            # 분류된 텍스트 태그로 라인 필터링
            _spans = filter_spans(_spans, WHITELIST)

            # 라인을 모아서 페이지 단위로 취합
            md = markdown(_spans)

            # pages.append(page_data)
            yield page_idx, md

    doc.close()

    # result = ""
    # for index, page in enumerate(pages):
    #     result += page

    # return result
