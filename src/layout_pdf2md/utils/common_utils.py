import time
import inspect
import os
import logging
from functools import wraps
from typing import List, Dict, Any, Tuple

logger = logging.getLogger(__name__)

try:
    import psutil

except Exception as e:
    logger.info("please install the psutil package.")


def log_mem(tag=""):
    p = psutil.Process(os.getpid())
    logger.info(f"[{tag}] {p.memory_info().rss / 1024 / 1024:.2f} MB")


def mem(func):
    if inspect.iscoroutinefunction(func):

        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                log_mem(f"START: {func.__name__}: {func.__doc__}")
                result = await func(*args, **kwargs)
                log_mem(f"END: {func.__name__}: {func.__doc__}")
                return result
            except Exception as e:
                result = await func(*args, **kwargs)
                return result

    else:

        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                log_mem(f"START: {func.__name__}: {func.__doc__}")
                result = func(*args, **kwargs)
                log_mem(f"END: {func.__name__}: {func.__doc__}")
                return result
            except Exception as e:
                result = func(*args, **kwargs)
                return result

    return wrapper


def sort_y(spans):
    """같은 라인에 있는 span들을 결합한다"""
    __y0 = lambda s: s["bbox"][1]
    __x0 = lambda s: s["bbox"][0]
    __font_size = lambda s: s["size"]
    __spans = sorted(spans, key=lambda s: (__y0(s), __x0(s), __font_size(s)))
    return __spans


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
    # return sorted(spans, key=lambda s: (y0(s), x0(s), font_size(s)))
    return sorted(spans, key=lambda s: (y0(s), x0(s)))


def timer(func):
    if inspect.iscoroutinefunction(func):

        @wraps(func)
        async def wrapper(*args, **kwargs):
            start = time.time()
            result = await func(*args, **kwargs)
            end = time.time()
            logger.info(f"[timer] {func.__name__} runtime: {end - start:.2f} sec.")
            return result

    elif inspect.isgeneratorfunction(func):

        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            count = 0

            for item in func(*args, **kwargs):
                count += 1
                yield item

            elapsed = time.perf_counter() - start
            logger.info(
                f"[timer-iter] {func.__name__} runtime: {elapsed:.2f} sec., items={count}"
            )

    else:

        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            result = func(*args, **kwargs)
            end = time.time()
            logger.info(f"[timer-sync] {func.__name__} runtime: {end - start:.2f} sec.")
            return result

    return wrapper
