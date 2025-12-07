from collections import Counter
from typing import List, Any, Dict, Tuple
import re
from collections import defaultdict
from .table_analizer import classify_span_with_tables
from .caption_analizer import is_side_caption, detect_side_caption_zones


page_num_pattern = re.compile(r"^[-–]?\s*\d+\s*[-–]?$")

# 1, 10, 3/24, 3 / 24 같은 형태까지 허용
PAGE_NUM_RE = re.compile(r"^\d{1,4}(\s*[/\-]\s*\d{1,4})?$")


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


def collect_header_footer_candidates(doc):
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


def _collect_span_style_stats(doc) -> Tuple[Counter, Counter]:
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


def get_body_font_style(doc) -> Dict[str, float | int]:
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
    size_counter, color_counter = _collect_span_style_stats(doc)

    # 가장 흔한 폰트 크기
    body_font_size = size_counter.most_common(1)[0][0] if size_counter else None

    # 가장 흔한 폰트 색상
    body_font_color = color_counter.most_common(1)[0][0] if color_counter else None

    return {
        "font_size": body_font_size,
        "font_color": body_font_color,
    }


def classify_span(span, body_font_size, body_font_color, page_h, page_w, tables: List[Any], ratios: Dict[str, float]) -> str:
    font_size = span["size"]
    font_color = span["color"]
    flags = span["flags"]
    text = span["text"].strip()

    font_name = span["font"].lower()
    is_bold = ("bold" in font_name) or ("bd" in font_name)
    
    if _is_page_number_span(span, page_h, page_w):
        return "[page_number]"

    if not text:
        return "[empty]"
    
    # 테이블 영역 판별
    if len(tables) > 0:
        table_prefix = classify_span_with_tables(span, tables)
        if table_prefix is not None:
            return table_prefix

    # 제목 (본문보다 확실히 큰 사이즈)
    if font_size >= body_font_size + 2 and (
        is_bold or (len(text) > 3 and len(text) < 30)
    ):
        return "[title]"

    # 소제목 (본문과 비슷한 크기이지만, 색상이 다르거나 볼드체)
    if (
        font_size >= body_font_size - 0.5
        and not (font_color == 0 or font_color == body_font_color)
        and (is_bold or (len(text) > 3 and len(text) < 30))
    ):
        return "[subtitle]"

    # if "1974.5.20." in text:
    #     print(span)
        
    # 캡션 / 각주 (본문 폰트 크기 보다 조금 크거나 작을수도 있음)
    if is_side_caption(
            span=span,
            body_font_size=body_font_size,
            page_h=page_h,
            page_w=page_w,
            left_zone_ratio=ratios["left_zone_ratio"],
            right_zone_ratio=ratios["right_zone_ratio"],
            caption_y_ratio=ratios["caption_y_ratio"],
            max_caption_len=120,
            pattern=None,
        ):
        return "[caption]"

    # 기본은 본문
    return "[body]"


def sanitize_spans(spans, opts: Dict[str, Any]) -> List[Dict]:
    """
    normalize spans by classifying them into categories
    Args:
        spans (List[Dict]): list of span objects
        opts (Dict): options including body_font_size, body_font_color, page_h, page_w
    Returns:
        List[Dict]: list of normalized span objects
    """
    result = []
    body_font_size: float = opts["body_font_size"]
    body_font_color: float = opts["body_font_color"]
    page_h: float = opts["page_h"]
    page_w: float = opts["page_w"]
    tables: List[Any] = opts.get("tables", [])
    ratios: Dict[str, float] = opts.get("caption_zones", {
        "left_zone_ratio": None,
        "right_zone_ratio": None,
        "caption_y_ratio": None,
    })

    for span in spans:
        text = span.get("text", "")
        span["text"] = (
            classify_span(span, body_font_size, body_font_color, page_h, page_w, tables, ratios)
            + text.strip()
            + "\n"
        )
        result.append(span)

    return result
