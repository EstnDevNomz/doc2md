from collections import Counter
from typing import List, Any, Dict, Tuple
import re
from collections import defaultdict


page_num_pattern = re.compile(r"^[-–]?\s*\d+\s*[-–]?$")

# 기본 캡션 패턴 예시: "<...>", "그림 1", "도표 3" 같은 것들
DEFAULT_SIDE_CAPTION_PATTERN = re.compile(
    r"(그림|도표|Figure|Fig\.?|Table)\s*\d+",
    re.IGNORECASE,
)

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


def is_side_caption(
    span: Dict,
    body_font_size: float,
    page_h: float,
    page_w: float,
    left_zone_ratio: float = 0.30,
    right_zone_ratio: float = 0.08,
    caption_y_ratio: float = 0.02,
    max_caption_len: int = 120,
    pattern: re.Pattern | None = None,
) -> bool:
    """
    PDF 페이지의 왼쪽/오른쪽 끝 영역에 위치한 사이드 캡션(설명 텍스트)인지 판별하는 함수

    Args:
        *span (Dict): pymupdf span 정보 딕셔너리
        *body_font_size (float): 본문 폰트 크기
        *page_h (float): 페이지 높이
        *page_w (float): 페이지 너비
        left_zone_ratio (float): 왼쪽 사이드 캡션 영역 비율 (0~1), 예: 0.25 → 왼쪽 25%
        right_zone_ratio (float): 오른쪽 사이드 캡션 영역 비율 (0~1), 예: 0.2 → 오른쪽 20%
        caption_y_ratio (float): 상하단 머리말/꼬리말 영역 제외 비율 (0~1)
        max_caption_len (int): 캡션 텍스트 최대 길이
        pattern (re.Pattern | None): 캡션을 판별할 정규식 패턴

    Returns:
        bool: 사이드 캡션으로 판단되면 True, 아니면 False
    """
    if pattern is None:
        pattern = DEFAULT_SIDE_CAPTION_PATTERN

    text = (span.get("text") or "").strip()
    if not text:
        return False

    font_size = span.get("size")
    bbox = span.get("bbox")
    if font_size is None or bbox is None:
        return False

    x0, y0, x1, y1 = bbox

    # 2-up-layout: 우측 페이지의 좌표를 좌측 페이지 기준으로 변환
    if x0 > page_w:
        x0 = x0 - page_w
        x1 = x1 - page_w

    x_center = (x0 + x1) / 2
    y_center = (y0 + y1) / 2

    # 상단/하단 머리말/꼬리말, 페이지 번호 영역은 제외 (필요 없으면 caption_y_ratio=0으로)
    vertical_margin = page_h * caption_y_ratio
    if y_center < vertical_margin or y_center > page_h - vertical_margin:
        return False

    # 좌/우 사이드 영역 정의
    left_zone_end = page_w * left_zone_ratio
    right_zone_start = page_w * (1.0 - right_zone_ratio)

    is_left_side = x_center <= left_zone_end
    is_right_side = x_center >= right_zone_start

    if not (is_left_side or is_right_side):
        # 중앙 영역에 있으면 사이드 캡션이 아님
        return False

    # 캡션 특성 조건들
    is_body_or_smaller = font_size <= body_font_size
    reasonable_length = len(text) <= max_caption_len

    # 정규식 패턴 매칭 시 바로 캡션 인정
    if pattern.search(text):
        return True

    # 패턴이 아니더라도, 사이드 영역 + 본문 이하 크기 + 너무 긴 문장이 아니면 캡션으로 취급
    if reasonable_length:
        return True

    return False


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


def classify_span(span, body_font_size, body_font_color, page_h, page_w):
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

    # 캡션 / 각주 (본문보다 확실히 작은 사이즈)
    if is_side_caption(span, body_font_size, page_h, page_w):
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

    for span in spans:
        text = span.get("text", "")
        span["text"] = (
            classify_span(span, body_font_size, body_font_color, page_h, page_w)
            + text.strip()
            + "\n"
        )
        result.append(span)

    return result
