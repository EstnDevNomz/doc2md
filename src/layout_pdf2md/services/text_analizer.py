import re
import math
import logging
from collections import Counter, defaultdict
from layout_pdf2md import *
from typing import List, Any, Dict, Tuple
from .table_analizer import classify_span_with_tables
from .caption_analizer import is_side_caption, detect_side_caption_zones


logger = logging.getLogger(__name__)


def _is_page_number_span(span, page_h, page_w, bottom_ratio: float = 0.08):
    """
    span 하나가 '페이지 하단의 페이지 번호'인지 판단
    - 숫자 형태인지
    - 페이지 하단(bottom_ratio 영역) 안에 있는지

    Args:
        span (Dict): span object
        page_h (float): page height
        page_w (_type_): page width
        bottom_ratio (float, optional): 쪽번호 영역 설정. Defaults to 0.08.

    Returns:
        bool: True if span is page number else False
    """
    if not span.get("bbox"):
        return False

    x0, y0, x1, y1 = span["bbox"]
    text = span["text"].strip()

    # 1) 숫자/페이지번호처럼 생긴 문자열 아니면 탈락
    if not PAGE_NUM_RE.match(text):
        return False

    # 2) 세로 위치: 페이지 하단 N% 영역만 허용
    y_center = (y0 + y1) / 2
    bottom_start = page_h * (1 - bottom_ratio)
    if y_center < bottom_start:
        return False

    # # 3) 가로 위치: 페이지 중앙 근처만 허용 (좌우 25% 안)
    # x_center = (x0 + x1) / 2
    # dist_from_center = abs(x_center - page_w / 2)
    # if dist_from_center > page_w * 0.25:
    #     return False

    return True


@atimeit
async def collect_header_footer_candidates(doc):
    pos_dict = defaultdict(list)  # (rounded_y, text) -> [page_idx...]

    for page_idx, page in enumerate(doc):
        page_h = page.rect.height
        blocks = page.get_text("dict")["blocks"]

        for b in blocks:
            if b["type"] != 0:
                continue

            for line in b["lines"]:
                y0 = line["bbox"][1]
                y_key = round(y0, 1)
                line_text = "".join(s["text"] for s in line["spans"]).strip()

                if not line_text:
                    continue

                pos_dict[(y_key, line_text)].append(page_idx)

    # 여러 페이지에 반복되는 것만
    header_footer = {
        key: pages
        for key, pages in pos_dict.items()
        if len(set(pages)) >= 3  # 3페이지 이상 반복되면 header/footer로 간주
    }

    return header_footer


@atimeit
async def _collect_span_style_stats(doc) -> Tuple[Counter, Counter]:
    """
    __summary__
    PDF 문서에서 span 단위의 폰트 크기와 색상을 수집하여 통계화하는 함수

    Args:
        doc (fitz.Document): pymupdf Document 객체

    Returns:
        Tuple[Counter, Counter]:
            - 폰트 크기 등장 빈도 Counter
            - 폰트 색상 등장 빈도 Counter
    """
    size_counter: Counter = Counter()
    color_counter: Counter = Counter()

    # 최대 50페이지까지만 스캔하여 성능 확보
    for i, page in enumerate(doc):
        if i > 50:
            break

        page_dict = page.get_text("dict")
        blocks = page_dict.get("blocks", [])

        for block in blocks:
            # type==0: 텍스트
            if block.get("type") != 0:
                continue

            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    # 폰트 크기 수집
                    size = span.get("size")
                    text = span.get("text", "").strip()

                    if size and len(text) > 30:
                        size_counter[round(size, 1)] += 1

                    # 폰트 색상 수집
                    # color 값은 정수형 RGB... fitz는 색을 0xRRGGBB 형태의 int로 제공
                    color = span.get("color")
                    if color is not None:
                        color_counter[color] += 1

    return size_counter, color_counter


@atimeit
async def get_body_font_style(doc) -> Dict[str, float | int]:
    """
    __summary__
    문서 전체에서 '본문'으로 추정되는 가장 흔한 폰트 크기와 색상을 반환

    Args:
        doc (fitz.Document): pymupdf Document 객체

    Returns:
        Dict[str, float | int]:
            {
                "font_size": float,  # 본문 폰트 크기
                "font_color": int,   # 본문 폰트 색상 (0xRRGGBB)
            }
    """
    size_counter, color_counter = await _collect_span_style_stats(doc)

    # 가장 흔한 폰트 크기
    body_font_size = size_counter.most_common(1)[0][0] if size_counter else None

    # 가장 흔한 폰트 색상
    body_font_color = color_counter.most_common(1)[0][0] if color_counter else None

    return {
        "font_size": body_font_size,
        "font_color": body_font_color,
    }


def _classify_span(span, **opts) -> str:
    """
    span의 타입을 분류한다

    Args:
        span (Dict): span 객체

    Returns:
        str: span type
    """
    body_font_size: float = opts.get("body_font_size", 10)
    body_font_color: float = opts.get("body_font_color", 0)
    page_w: float = opts.get("page_w", 0)
    page_h: float = opts.get("page_h", 0)
    tables: List[Any] = opts.get("tables", [])
    ratios: Dict[str, float] = opts.get("caption_zones", {})
    max_font_size: float = opts.get("max_font_size", 40)

    font_size = span["size"]
    font_color = span["color"]
    flags = span["flags"]
    text = span["text"].strip()

    font_name = span["font"].lower()
    is_bold = ("bold" in font_name) or ("bd" in font_name)

    if _is_page_number_span(span, page_h, page_w):
        return PAGE_NUMBER

    if not text:
        return EMPTY

    # 테이블 영역 판별
    if len(tables) > 0:
        table_prefix = classify_span_with_tables(span, tables, page_w=page_w)
        if table_prefix is not None:
            return table_prefix

    # H1 (본문보다 확실히 큰 사이즈)
    if font_size >= body_font_size + 2 and (
        is_bold or (len(text) > 3 and len(text) < max_font_size)
    ):
        return H1

    # H2 (본문과 비슷한 크기이지만, 색상이 다르거나 볼드체)
    if (
        font_size >= body_font_size - 0.5
        and not (font_color == 0 or font_color == body_font_color)
        and (is_bold or (len(text) > 3 and len(text) < max_font_size))
    ):
        return H2

    # # H3 (본문과 비슷한 크기이지만, 색상이 다르거나 볼드체)
    # if (
    #     font_size >= body_font_size
    #     and not (font_color == 0 or font_color == body_font_color)
    #     and (is_bold or (len(text) > 3 and len(text) < max_font_size))
    # ):
    #     return H3

    # 캡션 / 각주 (본문 폰트 크기 보다 조금 크거나 작을수도 있음)
    if is_side_caption(
        span=span,
        body_font_size=body_font_size,
        page_h=page_h,
        page_w=page_w,
        left_zone_ratio=ratios["left_zone_ratio"],
        right_zone_ratio=ratios["right_zone_ratio"],
        caption_y_ratio=ratios["caption_y_ratio"],
        max_caption_len=35,
        pattern=None,
    ):
        return CAPTION

    # 기본은 본문
    return BODY


@timeit
def classify_spans(spans: List[Dict], **opts: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    normalize spans by classifying them into categories

    Args:
        spans (List[Dict]): list of span objects
        opts (Dict): options including body_font_size, body_font_color, page_h, page_w
    Returns:
        List[Dict]: list of normalized span objects
    """
    result = []

    # tokenizing
    for i, span in enumerate(spans):
        _text = span.get("text", "")
        _type = _classify_span(span, **opts)
        span["_type"] = _type if _type else ""
        span["text"] = _text.strip() + "\n"
        result.append(span)

    return result


def filter_spans(spans: List[Dict], filters_ls: List[str]) -> List[Dict]:
    """
    filter spans by span's _type

    Args:
        spans (List[Dict]): span list
        filters_ls (List[str]): whitelist

    Returns:
        List[Dict]: filtered spans
    """
    results = []

    for span in spans:
        _text = span.get("text", "")

        if span["_type"] in filters_ls:
            results.append(span)

    return results


@timeit
def markdown(spans: List[Dict]) -> str:
    """
    spans -> 마크다운 포맷

    Args:
        spans (List[Dict]): span 객체 리스트

    Returns:
        str: markdown text
    """
    for i, span in enumerate(spans):
        if span.get("_type") == H1:
            sep = (
                f"<{SEP}>"
                if i > 0
                and spans[i - 1]["_type"] not in [H1, H2]
                and len(span["text"]) > 3
                else ""
            )
            span["text"] = f'{sep}# {span["text"]}'
            continue

        if span.get("_type") == H2:
            sep = (
                f"<{SEP}>"
                if i > 0
                and spans[i - 1]["_type"] not in [H1, H2]
                and len(span["text"]) > 3
                else ""
            )
            span["text"] = f'{sep}## {span["text"]}'
            continue

        # if span.get("_type") == "h3":
        #     span["text"] = f'### {span["text"]}'
        #     continue

        if span.get("_type") == BODY:
            meta = (
                f"<{META}>"
                if i > 0 and spans[i - 1]["_type"] in [H1, H2] and len(span["text"]) > 3
                else ""
            )
            span["text"] = f'{meta}{span["text"]}'

            continue

        if span.get("_type") == PAGE_NUMBER:
            span["text"] = f'[{span.get("_type", "")}] {span["text"]}'
            continue

        span["text"] = f'[{span.get("_type", "")}] {span.get("text", "")}'

    _spans = [s.get("text", "") for s in spans]
    return "".join(_spans)


@timeit
def analize_morphemes(text: str, topk: int, min_token: int = 50) -> List[str]:
    results = []

    try:
        from kiwipiepy import Kiwi

        kiwi = Kiwi()
        results = kiwi.analyze(text)
    except Exception as e:
        logger.warn("Please install kiwipiepy package..")
        return []

    kiwi = Kiwi()
    results = kiwi.analyze(text)

    if not results:
        return []

    tokens = results[0][0]
    if len(tokens) < min_token:
        return []

    nouns = [t.form for t in tokens if t.tag in ("NNG", "NNP", "SL", "SN")]
    bigrams = [f"{nouns[i]} {nouns[i+1]}" for i in range(len(nouns) - 1)]
    freq = Counter(bigrams)
    top_terms = [w for w, _ in freq.most_common(topk)]

    return top_terms


def normalize_synonym_tokens(doc, syn_map):
    """
    동의어 정규화: syn_map 의존
    """
    return [syn_map.get(t, t) for t in doc]


@timeit_iter
def iter_tf_idf_keywords(tokenized_docs: List[str], topk: int = 10):
    """
    TF-IDF 수행한다; 형태소 품질에 100% 의존
    tokenized_docs: List[List[str]]  # 문서별 토큰 리스트(명사 등)
    return: List[List[tuple[str, float]]]
    """
    N = len(tokenized_docs)

    # DF: 단어가 등장한 문서 수
    df = defaultdict(int)
    for doc in tokenized_docs:
        for term in set(doc):
            df[term] += 1

    # IDF: log((N+1)/(df+1)) + 1  (스무딩)
    idf = {t: math.log((N + 1) / (df_t + 1)) + 1 for t, df_t in df.items()}

    for i, doc in enumerate(tokenized_docs):
        tf = Counter(doc)
        doc_len = len(doc) or 1

        # TF: 빈도/문서길이 (정규화)
        scores = {t: (tf[t] / doc_len) * idf.get(t, 0.0) for t in tf}

        # 점수 기준 내림차순 정렬 - 상위 topk개만 유지
        top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:topk]

        yield i, top
