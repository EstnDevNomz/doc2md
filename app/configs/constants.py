# ===
# name: Constants
# desc: 상수명은 반드시 대문자로 선언
# release version: v0.1.0
# author: Lee
# regdate: 2025-12-13
# moddate: 2025-12-13
# ===

# pymupdf에서 추출된 dict 객체 분류
TEXT = 0
IMG = 1

import re

UNIT_PATTERN = re.compile(r"^\s*\(단위\s*[:：]", re.UNICODE)

# 기본 캡션 패턴 예시: "<...>", "그림 1", "도표 3" 같은 것들
DEFAULT_SIDE_CAPTION_PATTERN = re.compile(
    r"(그림|도표|Figure|Fig\.?|Table)\s*\d+",
    re.IGNORECASE,
)
page_num_pattern = re.compile(r"^[-–]?\s*\d+\s*[-–]?$")

# 1, 10, 3/24, 3 / 24 같은 형태까지 허용
PAGE_NUM_RE = re.compile(r"^\d{1,4}(\s*[/\-]\s*\d{1,4})?$")


from typing import Tuple

BBOX = Tuple[float, float, float, float]  # (x0, y0, x1, y1)

# span 타입
PAGE_NUMBER = "page-number"
EMPTY = "empty"
H1 = "h1"
H2 = "h2"
H3 = "h3"
CAPTION = "caption"
BODY = "body"
TABLE_UNIT = "table-unit"
TABLE_SUBJECT = "table-subject"
TABLE_HEADER = "table-header"
SEP = "SEP"
META = "META"

# MD 생성시 허용되는 span 타입
WHITELIST = [
    # PAGE_NUMBER,
    H1,
    H2,
    # CAPTION,
    BODY,
    SEP,
]

# 페이지 세로 수직 분할시 최소 너비 제한
MIN_RAIL_WIDTH = 4

# 동의어 정규화
SYN_MAP = {
    "농업협동조합": "농협",
    "농촌 농": "농촌 농협",
    "농 회": "농협 회장",
    "사 발간": "60년사 발간",
}
