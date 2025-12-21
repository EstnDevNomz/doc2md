# ---
# name: [변환기] PDF > MD
# desc: PDF 데이터를 LLM 친화적으로 재해석
# release version: v0.1.1
# author: Lee
# regdate: 2025-12-15
# moddate: 2025-12-16
# ---

import os
import re
import copy
import glob
import logging
import fitz
import html2text
from layout_pdf2md import *
from typing import *
from .services.text_box_clustering import (
    cluster_by_x_rails,
    get_y_rails,
    _classify_spans_by_splited_page,
)
from .services.caption_analizer import detect_side_caption_zones
from .services.text_analizer import (
    markdown,
    classify_spans,
    filter_spans,
    analyze_doc_meta,
    analyze_doc_style,
    analize_morphemes,
    normalize_synonym_tokens,
    iter_tf_idf_keywords,
)
from .domains.syntax_rules import page_number

logger = logging.getLogger(__name__)


@timer
def pdf2md(file_path) -> None:
    """실행 함수
    Args:
        file_path (str): 파일 경로
    """
    logger.info(f"pdf2md > started\nfile_path: {file_path}")
    name, ext = os.path.splitext(file_path)

    # PDF 추상 객체를 가져온다
    total_index, ast = get_pdf_ast_from(file_path)
    logger.info(f"pdf2md > get_pdf_ast_from > extracted {total_index} AST")

    # [PDF 구조분석] 집계데이터 생산라인 -> 파이프라인 ingestion
    doc_meta = analyze_doc_meta(ast)
    body_styles = analyze_doc_style(ast)  # 본문 폰트 크기

    file_text: str = ""
    # [정규화] run file streaming
    for page_idx, page in iter_page_pipeline(ast, doc_meta, body_styles):
        file_text += page
        logger.debug(
            f"pdf2md > [generator] iter_page_pipeline > page {page_idx+1}/{total_index} successed"
        )

    logger.info(f"pdf2md > page {total_index} successed")
    ast.close()

    # 형태소분석(불용어, 복합병사 2-gram 보정) -> TF-IDF 분류 -> 라벨링
    with open(f"{name}.md", "w", encoding="utf-8") as f:
        _morphemes: List[List[str]] = []

        # 특정 문자열로 섹션을 분할한다
        sections = file_text.split(f"<{SEP}>")
        del file_text

        for section in sections:
            # 섹션 단위 형태소 분석
            _nouns = analize_morphemes(section, 30)
            _morphemes.append(_nouns)
            _nouns = []
            logger.debug(
                f"pdf2md > analize_morphemes > page {page_idx+1}/{total_index} successed"
            )

        # 명사 동의어 표준화
        morphemes = [normalize_synonym_tokens(doc, SYN_MAP) for doc in _morphemes]
        logger.info(
            f"pdf2md > normalize_synonym_tokens > nouns {len(_morphemes)} successed"
        )
        del _morphemes

        # TF-IDF 수행하여 도메인 후보 명사를 추출 -> Meta 필드 추가
        for i, keywords in iter_tf_idf_keywords(morphemes, 3):
            if len(sections[i]) > MIN_SECTION_LEN or len(keywords) > 0:
                page_number_matches = list(page_number.scan_string(sections[i]))
                _meta: str = ""
                if page_number_matches:
                    tokens, start, end = page_number_matches[0][0]
                    page_mark = tokens.get("page_mark")
                    sections[i] = re.sub(page_mark, "", sections[i])
                    _meta += page_mark if page_mark else ""
                
                _keys = [k[0] for k in keywords]
                _meta += f'[{KEYWORDS}] {",".join(_keys)}\n' if _keys else ""
                
                # 메타 임시 필드 교체
                sections[i] = re.sub(f"<{META}>", _meta, sections[i])
            else:
                # 본문 내용이 너무 없으면 메타 안넣음
                sections[i] = re.sub(f"<{META}>", "", sections[i])

            f.write(sections[i])

            logger.debug(
                f"pdf2md > [generator] iter_tf_idf_keywords > section {i} successed"
            )

        # with open(f"형태소분석_2_gram.md", "a") as f:
        #     f.write(str(keywords_ls) + "\n")

        logger.info(f"pdf2md > page {total_index} successed")


@mem
@timer
def get_pdf_ast_from(file_path: str):
    """PDF파싱"""
    ast = fitz.open(file_path)
    return ast.page_count, ast


@timer
@mem
def iter_page_pipeline(
    doc: fitz.Document, doc_meta: Dict, body_styles: Dict[str, float]
):
    """제너레이터(PDF -> MD)"""
    body_font_size = body_styles["body_font_size"]
    body_font_color = body_styles["body_font_color"]

    stitched_vertical_md: str = ""

    # 페이지 단위 데이터 스트리밍을 시작한다
    for page_idx in range(doc.page_count):
        page = doc.load_page(page_idx)
        page_w = page.rect.width
        page_h = page.rect.height
        dicts = page.get_text("dict")
        table_object = page.find_tables()

        # 이미지 블록은 제외한다
        _blocks = [block for block in dicts["blocks"] if block.get("type") == TEXT]
        _lines = [block.get("lines", []) for block in _blocks]
        _span_groups = [
            line.get("spans", []) for line_group in _lines for line in line_group
        ]
        _spans = [span for span_group in _span_groups for span in span_group]
        opts = {
            "body_font_size": body_font_size,
            "page_w": page_w,
            "page_h": page_h,
        }
        # detect side caption zones
        caption_zones = detect_side_caption_zones(_spans, **opts)
        opts["caption_zones"] = caption_zones
        opts["body_font_color"] = body_font_color
        opts["tables"] = table_object.tables
        opts["doc_meta"] = doc_meta

        del dicts, _blocks, page

        # 세로 절개 기준선 목록을 얻는다
        y_rails: List[float] = get_y_rails(_spans, padding=1, min_count=10)

        for i, rail in enumerate(y_rails):
            # 절개선 기준으로 "오른쪽 영역"을 재귀적으로 절개하여 "왼쪽 영역"의 spans를 모은다
            left_spans, right_spans = _classify_spans_by_splited_page(
                _spans, page_w, rail
            )
            # split_width = rail - y_rails[i - 1]
            # len_y_rail = len(y_rails) - 1

            # if MIN_RAIL_WIDTH < split_width:
            #     left_spans = []

            # if len(left_spans) < 5:
            #     left_spans = []

            # 왼쪽 영역 spans를 누적 -> 왼쪽 영역부터 순서대로 y 정렬되는 효과
            if left_spans:
                md = preprocess(left_spans, **opts)
                yield page_idx, md

            # 다음 페이지 분할을 위해 오른쪽 spans를 타겟으로 세팅한다
            _spans = right_spans
            
        md = preprocess(_spans, **opts)
        
        yield page_idx, md


def preprocess(spans, **opts):
    # [라벨링] span 단위로 텍스트 분류 태깅
    spans = classify_spans(spans, **opts)

    # [필터링] 분류된 텍스트 태그로 라인 필터링
    spans = filter_spans(spans, WHITELIST)

    # 스팬을 까서 마크다운 생성한다
    md = markdown(sort_y(spans))
    md = re.sub(r"\s?·\s?", "·", md)
    
    return md