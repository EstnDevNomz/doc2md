import time
from functools import wraps


def timeit(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        end = time.time()
        print(f"[timer] {func.__name__} runtime: {end - start:.2f} sec.")
        return result   # 이것도 중요
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
