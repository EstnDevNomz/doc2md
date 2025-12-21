from pyparsing import (
    Word,
    nums,
    Regex,
    Literal,
    Optional,
    restOfLine,
    Suppress,
    White,
    Combine,
    ParserElement,
    oneOf,
    ParseException,
)
from ..configs.constants import PAGE_NUMBER

# ---
# 공통 토큰 정의
# ---
# 날짜 패턴 yyyy.m.d. 또는 yyyy.mm.dd.
date_token = Combine(
    Word(nums, exact=4)
    + "."
    + Word(nums, min=1, max=2)
    + "."
    + Word(nums, min=1, max=2)
    + Optional(".")
).set_results_name("date")


page_number = (
    Word(f"[{PAGE_NUMBER}]")
    + White()
    + Word(nums, min=1, max=3)
).set_results_name("page_mark")
