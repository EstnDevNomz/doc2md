import time
from functools import wraps
from typing import List, Dict, Any, Tuple


def sort_spans_by_layout(spans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Y좌표와 X좌표 기준으로 span들을 레이아웃 순서대로 정렬

    Args:
        spans (List[Dict[str, Any]]): span 리스트

    Returns:
        List[Dict[str, Any]]: 정렬된 span 리스트
    """
    # bbox: [x0, y0, x1, y1]
    y0 = lambda s: s["bbox"][1]
    x0 = lambda s: s["bbox"][0]
    font_size = lambda s: s["size"]

    # 파서가 읽은 span 리스트를 y > x > font_size 순으로 재정렬
    return sorted(spans, key=lambda s: (y0(s), x0(s), font_size(s)))


def timeit(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        end = time.time()
        print(f"[timer] {func.__name__} runtime: {end - start:.2f} sec.")
        return result  # 이것도 중요

    return wrapper


# timer for asynchronous function
def atimeit(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        start = time.time()
        result = await func(*args, **kwargs)
        end = time.time()
        print(f"[timer-async] {func.__name__} runtime: {end - start:.2f} sec.")
        return result

    return wrapper


# timer for generator
def timeit_iter(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        count = 0

        for item in func(*args, **kwargs):
            count += 1
            yield item

        elapsed = time.perf_counter() - start
        print(
            f"[timer-iter] {func.__name__} runtime: {elapsed:.2f} sec., items={count}"
        )

    return wrapper
