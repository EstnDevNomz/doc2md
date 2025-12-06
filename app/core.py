# ====
# name: [변환기] PDF > MD
# desc: PDF 데이터를 LLM 친화적으로 재해석
# release version: v0.1.0
# author: Lee
# regdate: 2025-12-04
# ====
import os
import re
import copy
import glob
import logging
import fitz
import html2text

# from .config.constants import

from typing import List, Any, Dict
from .services.text_analizer import *

TEXT = 0
IMG = 1


def filter_img_blocks(blocks):
    """
    filter image blocks
    """
    results = []
    for b in blocks:
        if b["type"] == TEXT:
            results.append(b)
    return results


def get_lines(blocks):
    lines = []
    for block in blocks:
        lines += [line for line in block["lines"]]
    return lines


def sort_spans_by_layout(spans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    __summary__
    Y좌표와 X좌표 기준으로 span들을 레이아웃 순서대로 정렬

    Args:
        spans (List[Dict[str, Any]]): span 리스트

    Returns:
        List[Dict[str, Any]]: 정렬된 span 리스트
    """
    # bbox: [x0, y0, x1, y1]
    return sorted(spans, key=lambda s: (s["bbox"][1], s["bbox"][0], s["size"]))


def get_md_by_pdf(file_path: str):
    doc = fitz.open(file_path)
    logging.info(f"Total page count:", doc.page_count)
    pages: List[str] = []

    # TODO: 헤더 푸터 메타로 활용 예정
    header_or_footer = collect_header_footer_candidates(doc)

    # 본문 폰트 크기
    body_styles = get_body_font_style(doc)

    for i in range(doc.page_count):
        page = doc.load_page(i)
        dicts = page.get_text("dict")
        # words = page.get_text("words")

        blocks = filter_img_blocks(dicts["blocks"])
        lines = get_lines(blocks)

        if len(lines) == 0:
            continue

        spans = []
        for line in lines:
            spans += [span for span in line["spans"]]

        solted_spans = sort_spans_by_layout(spans)

        # If the page is landscape (wider than tall), split it vertically into
        # two halves (left then right) and treat each half as its own page
        # so the reading order is preserved for two-column/landscape scans.
        page_w = page.rect.width
        page_h = page.rect.height

        if page_w > page_h:
            mid_x = page_w / 2.0

            left_spans = []
            right_spans = []

            for s in solted_spans:
                bbox = s.get("bbox")
                if bbox and len(bbox) >= 4:
                    x0, y0, x1, y1 = bbox[0], bbox[1], bbox[2], bbox[3]
                    center_x = (x0 + x1) / 2.0
                else:
                    # fallback: treat as left if no bbox
                    center_x = 0

                if center_x < mid_x:
                    left_spans.append(s)
                else:
                    right_spans.append(s)

            # Normalize and append left then right (skip empty halves)
            for sub_spans in (left_spans, right_spans):
                if not sub_spans:
                    continue
                cleand_spans = sanitize_spans(
                    sub_spans,
                    {
                        "body_font_size": body_styles["font_size"],
                        "body_font_color": body_styles["font_color"],
                        "page_h": page_h,
                        # use half width for normalization heuristics
                        "page_w": page_w / 2.0,
                    },
                )

                text = "".join([ss.get("text", "") for ss in cleand_spans])
                pages.append(text)
        else:
            cleand_spans = sanitize_spans(
                solted_spans,
                {
                    "body_font_size": body_styles["font_size"],
                    "body_font_color": body_styles["font_color"],
                    "page_h": page_h,
                    "page_w": page_w,
                },
            )

            text = "".join([s.get("text", "") for s in cleand_spans])
            pages.append(text)

    doc.close()

    result = ""
    for index, page in enumerate(pages):
        result += page

    return result
