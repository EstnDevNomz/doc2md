import re
from typing import Dict, Any, List, Tuple


# 기본 캡션 패턴 예시: "<...>", "그림 1", "도표 3" 같은 것들
DEFAULT_SIDE_CAPTION_PATTERN = re.compile(
    r"(그림|도표|Figure|Fig\.?|Table)\s*\d+",
    re.IGNORECASE,
)

BBox = Tuple[float, float, float, float]


def detect_side_caption_zones(
    spans: List[Dict[str, Any]],
    body_font_size: float,
    page_w: float,
    page_h: float,
    *,
    caption_font_scale: float = 0.95,
    max_caption_len: int = 120,
    min_candidates: int = 2,
    min_body_len: int = 20,
    symmetry_tol: float = 0.05,         # 좌우 여백 비율 차이가 이 이하면 "중앙 정렬" 취급
    max_side_ratio: float = 0.5,        # 안전 상한
    default_side_ratio: float = 0.12,   # 중앙 레이아웃에서 줄 최소 사이드 영역
) -> Dict[str, float]:
    """
    각 페이지에서 사이드 캡션이 차지하고 있는 영역 비율을 추정하는 함수.
    - 본문 영역을 먼저 추정해서, 본문이 차지하는 중앙/한쪽 몰림 여부를 보고
      좌/우 캡션 비율을 보정한다.
    - 이 문서군에서는 "사이드 캡션은 한쪽만 존재"한다는 가정도 반영.

    Returns:
        {
            "left_zone_ratio": float,   # 0~1, 왼쪽 캡션 영역 폭 / 전체 폭
            "right_zone_ratio": float,  # 0~1, 오른쪽 캡션 영역 폭 / 전체 폭
            "caption_y_ratio": float,   # 0~0.5, 상·하단 머리말/꼬리말로 제외할 비율
        }
    """
    # 페이지 사이즈 이상하면 그냥 기본값
    if page_w <= 0 or page_h <= 0:
        return {
            "left_zone_ratio": 0.08,
            "right_zone_ratio": 0.08,
            "caption_y_ratio": 0.02,
        }

    # -----------------------------
    # 1. 본문 후보 / 캡션 후보 분리
    # -----------------------------
    caption_candidates: List[Dict[str, Any]] = []
    body_boxes: List[BBox] = []
    ys: List[float] = []

    for span in spans:
        text = span.get("text", "").strip()
        if not text:
            continue

        size = float(span.get("size", body_font_size))
        x0, y0, x1, y1 = span["bbox"]

        # 2-up-layout: 우측 페이지 좌표를 좌측 기준으로 변환
        if x0 > page_w:
            x0 -= page_w
            x1 -= page_w

        # y 분포는 caption_y_ratio 계산용
        ys.extend([y0, y1])

        # 캡션 후보 조건
        is_caption_font = size <= body_font_size * caption_font_scale
        is_caption_len = len(text) <= max_caption_len

        if is_caption_font and is_caption_len:
            caption_candidates.append({
                "bbox": (x0, y0, x1, y1),
                "text": text,
                "size": size,
            })
            continue

        # 본문 후보 조건: 폰트는 거의 본문급, 길이도 어느 정도 이상
        if size >= body_font_size * 0.9 and len(text) >= min_body_len:
            body_boxes.append((x0, y0, x1, y1))

    # -----------------------------
    # 2. 캡션 후보가 아예 없으면 기본값
    # -----------------------------
    if not caption_candidates:
        return {
            "left_zone_ratio": 0.08,
            "right_zone_ratio": 0.08,
            "caption_y_ratio": 0.02,
        }

    # -----------------------------
    # 3. 본문 영역(bounding box) 추정
    # -----------------------------
    body_left = 0.0
    body_right = page_w

    if body_boxes:
        body_left = min(b[0] for b in body_boxes)
        body_right = max(b[2] for b in body_boxes)
        # 페이지 밖으로 나간 값 방어
        body_left = max(0.0, min(body_left, page_w))
        body_right = max(0.0, min(body_right, page_w))
    else:
        # 본문 추정 실패 시: 그냥 전체 폭을 본문으로 가정
        body_left = 0.0
        body_right = page_w

    left_margin = body_left
    right_margin = page_w - body_right
    left_margin_ratio = left_margin / page_w
    right_margin_ratio = right_margin / page_w

    # -----------------------------
    # 4. 캡션 후보 좌/우 분리 (본문 기준이 아닌 페이지 기준)
    # -----------------------------
    left_boxes: List[BBox] = []
    right_boxes: List[BBox] = []

    mid_x = page_w / 2.0

    for c in caption_candidates:
        x0, y0, x1, y1 = c["bbox"]
        cx = (x0 + x1) / 2.0

        if cx < mid_x:
            left_boxes.append((x0, y0, x1, y1))
        else:
            right_boxes.append((x0, y0, x1, y1))

    # -----------------------------
    # 5. 좌/우 raw 캡션 영역 계산
    # -----------------------------
    left_zone_ratio = 0.08
    if len(left_boxes) >= min_candidates:
        max_x1 = max(b[2] for b in left_boxes)  # 왼쪽 캡션의 오른쪽 경계
        left_zone_ratio = max_x1 / page_w
        left_zone_ratio = max(0.0, min(left_zone_ratio, max_side_ratio))

    right_zone_ratio = 0.08
    if len(right_boxes) >= min_candidates:
        min_x0 = min(b[0] for b in right_boxes)  # 오른쪽 캡션의 왼쪽 경계
        width = page_w - min_x0
        right_zone_ratio = width / page_w
        right_zone_ratio = max(0.0, min(right_zone_ratio, max_side_ratio))

    # -----------------------------
    # 6. 본문 여백 기반 보정
    #    - 캡션 영역은 본문을 침범하지 않도록 제한
    # -----------------------------
    # 왼쪽: 캡션 영역은 body_left까지만 허용
    if left_zone_ratio > 0:
        max_allowed_left = (body_left / page_w) * 1.05  # 약간의 여유
        left_zone_ratio = min(left_zone_ratio, max_allowed_left)

    # 오른쪽: 캡션 영역은 body_right 이후만
    if right_zone_ratio > 0:
        max_allowed_right = (page_w - body_right) / page_w * 1.05
        right_zone_ratio = min(right_zone_ratio, max_allowed_right)

    # -----------------------------
    # 7. "사이드 캡션은 한쪽만 존재" 규칙 적용
    # -----------------------------
    # 둘 다 0이면 그대로.
    if left_zone_ratio > 0 and right_zone_ratio > 0:
        # 본문 여백이 거의 대칭이면 → 중앙 본문 → 양쪽 모두 크게 나오면 안 됨
        if abs(left_margin_ratio - right_margin_ratio) <= symmetry_tol:
            # 둘 중 더 큰 쪽만 남기고, 나머지는 0으로
            if left_zone_ratio >= right_zone_ratio:
                right_zone_ratio = 0.08
            else:
                left_zone_ratio = 0.08
        else:
            # 비대칭 레이아웃이라도, 이 문서군에서는 한쪽만 사용
            if left_zone_ratio >= right_zone_ratio:
                right_zone_ratio = 0.08
            else:
                left_zone_ratio = 0.08

    # 중앙 정렬이고, 둘 다 너무 작으면 최소값으로 맞춰주는 것도 가능
    if (
        left_zone_ratio == 0.08
        and right_zone_ratio == 0.08
        and abs(left_margin_ratio - right_margin_ratio) <= symmetry_tol
    ):
        # 캡션이 있긴 한데 본문이 중앙이라 애매한 경우:
        # 그냥 양쪽 동일한 최소값으로 설정할 수도 있고,
        # 진짜 없는 걸로 볼 수도 있음. 여기선 그대로 0 두는 쪽 선택.
        pass

    # -----------------------------
    # 8. caption_y_ratio 계산
    # -----------------------------
    caption_y_ratio = 0.02
    if ys:
        min_y = min(ys)
        max_y = max(ys)
        top_margin = max(0.0, min_y) / page_h
        bottom_margin = max(0.0, (page_h - max_y)) / page_h
        caption_y_ratio = min(0.2, max(top_margin, bottom_margin) * 1.2)

    return {
        "left_zone_ratio": left_zone_ratio,
        "right_zone_ratio": right_zone_ratio,
        "caption_y_ratio": caption_y_ratio,
    }


def is_side_caption(
    span: Dict,
    body_font_size: float,
    page_h: float,
    page_w: float,
    left_zone_ratio: float = 0.24,
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

