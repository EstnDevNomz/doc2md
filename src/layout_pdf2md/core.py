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
from layout_pdf2md import *
from typing import *
from .services.text_box_clustering import cluster_by_x_rails, get_y_rails
from .services.caption_analizer import detect_side_caption_zones
from .services.text_analizer import (
    markdown,
    classify_spans,
    filter_spans,
    collect_header_footer_candidates,
    get_body_font_style,
    analize_morphemes,
    normalize_synonym_tokens,
    iter_tf_idf_keywords,
)

logger = logging.getLogger(__name__)


@timer
async def pdf2md(file_path) -> None:
    """실행 함수
    Args:
        file_path (str): 파일 경로
    """
    logger.info(f"[async] pdf2md > started\nfile_path: {file_path}")
    name, ext = os.path.splitext(file_path)

    # PDF 추상 객체를 가져온다
    total_index, ast = await get_pdf_ast_from(file_path)
    logger.info(f"[async] pdf2md > get_pdf_ast_from > extracted {total_index} AST")

    # PDF 전체 분석 집계 결과 -> 파이프라인 ingestion
    page_meta, body_styles = await analize_pdf(ast)

    file_text: str = ""
    # run file streaming: 정규화
    for page_idx, page in iter_page_pipeline(ast, page_meta, body_styles):
        file_text += page
        logger.debug(
            f"[async] pdf2md > [generator] iter_page_pipeline > page {page_idx+1}/{total_index} successed"
        )

    logger.info(f"[async] pdf2md > page {total_index} successed")
    ast.close()

    # 형태소분석(불용어, 복합병사 2-gram 보정) -> TF-IDF 분류 -> 라벨링
    with open(f"{name}.md", "w", encoding="utf-8") as f:
        _morphemes: List[List[str]] = []

        # <SEP> 태그로 섹션을 분할한다
        sections = file_text.split(f"<{SEP}>")
        del file_text

        for section in sections:
            # 섹션 단위 형태소 분석
            _nouns = analize_morphemes(section, 30)
            _morphemes.append(_nouns)
            _nouns = []
            logger.debug(
                f"[async] pdf2md > analize_morphemes > page {page_idx+1}/{total_index} successed"
            )

        # 명사 동의어 표준화
        morphemes = [normalize_synonym_tokens(doc, SYN_MAP) for doc in _morphemes]
        logger.info(
            f"[async] pdf2md > normalize_synonym_tokens > nouns {_morphemes} successed"
        )
        del _morphemes

        # TF-IDF 수행하여 도메인 후보 명사를 추출 -> Meta 필드 추가
        for i, keywords in iter_tf_idf_keywords(morphemes, 3):
            # 본문 내용이 너무 없으면 메타 안넣음
            if len(sections[i]) > 100 or len(keywords) > 0:
                _keys = [k[0] for k in keywords]
                _meta = f'[[META]] keywords: {",".join(_keys)}\n'
                sections[i] = re.sub(f"<{META}>", _meta, sections[i])
            else:
                sections[i] = re.sub(f"<{META}>", "", sections[i])

            f.write(sections[i])

            logger.debug(
                f"[async] pdf2md > [generator] iter_tf_idf_keywords > section {i} successed"
            )

        # with open(f"형태소분석_2_gram.md", "a") as f:
        #     f.write(str(keywords_ls) + "\n")

        logger.info(f"[async] pdf2md > page {total_index} successed")


@mem
async def get_pdf_ast_from(file_path: str):
    """PDF파싱"""
    ast = fitz.open(file_path)
    return ast.page_count, ast


@mem
async def analize_pdf(doc: fitz.Document):
    """PDF특징분석"""
    logger.info(f"[async] pdf2md > analize_pdf> start")
    
    tasks = [
        collect_header_footer_candidates(doc),  # TODO: 헤더 푸터 메타로 활용 예정
        get_body_font_style(doc),  # 본문 폰트 크기
    ]
    results = asyncio.gather(*tasks)
    logger.info(f"[async] pdf2md > analize_pdf> results: {results}")

    return await results


@mem
def iter_page_pipeline(doc: fitz.Document, page_meta: Dict, body_styles: Dict[str, float]):
    """제너레이터(PDF -> MD)"""
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
        target_spans = sort_spans_by_layout(spans)

        for i, rail in enumerate(y_rails):
            # 절개선 기준으로 "오른쪽 영역"을 재귀적으로 절개하여 "왼쪽 영역"의 spans를 모은다
            left_spans, right_spans = _classify_spans_by_splited_page(
                target_spans, page_w, rail
            )
            split_width = rail - y_rails[i - 1]
            len_y_rail = len(y_rails) - 1

            if 3 < split_width < MIN_RAIL_WIDTH:
                left_spans = []

            if len(left_spans) < 5:
                left_spans = []

            if left_spans:
                # 왼쪽 영역 spans를 누적 -> 왼쪽 영역부터 순서대로 y 정렬되는 효과
                arranged_spans += left_spans

            # 다음 페이지 분할을 위해 오른쪽 spans를 타겟으로 세팅한다
            target_spans = right_spans

        # 마지막 페이지도 모은다
        arranged_spans += target_spans

        opts1 = {
            "body_font_size": body_styles["font_size"],
            "page_w": page_w,
            "page_h": page_h,
            "page_meta": page_meta
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
            "page_meta": page_meta
        }
        # [태깅] span 단위로 텍스트 분류 태깅
        _spans = classify_spans(arranged_spans, **opts2)

        # [필터링] 분류된 텍스트 태그로 라인 필터링
        _spans = filter_spans(_spans, WHITELIST)

        # 스팬을 까서 마크다운 생성한다
        md = markdown(_spans)
        del page, dicts, table_object, arranged_spans, _spans, opts1, opts2, target_spans

        # 스트림 출력한다
        yield page_idx, md


def _classify_spans_by_splited_page(spans, page_w, y_rail):
    """분할된 페이지에서 spans를 분류한다 (분할선 기준 왼쪽 spans 반환)
    Args:
        spans (List[Dict]): source spans
        page_w (float): page width
        y_rail (float): coordinate of split rail
    Returns:
        List[Dict]: target spans
    """
    left_spans = []
    right_spans = []

    for s in spans:
        bbox = s.get("bbox")
        if bbox and len(bbox) >= 4:
            x0, y0, x1, y1 = bbox[0], bbox[1], bbox[2], bbox[3]

            # # 2-up-layout: 우측 페이지의 좌표를 좌측 페이지 기준으로 변환
            # if x0 > page_w:
            #     x0 = x0 - page_w
            #     x1 = x1 - page_w

            x1 = x1
        else:
            # fallback: treat as left if no bbox
            x1 = 0

        if x1 < y_rail:
            left_spans.append(s)
        else:
            right_spans.append(s)

    return left_spans, right_spans


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
