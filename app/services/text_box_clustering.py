from typing import List, Dict, Any, Tuple
from statistics import median
from collections import Counter

Span = Dict[str, Any]


def cluster_by_x_rails(
    spans: List[Span],
    *,
    x_gap_ratio: float = 0.06,  # 페이지 폭 대비 레일 간 간격
) -> List[List[Span]]:
    if not spans:
        return []

    # x 중심값
    xs = sorted(spans, key=lambda s: (s["bbox"][0] + s["bbox"][2]) / 2)
    page_w = max(s["bbox"][2] for s in spans)
    x_gap = page_w * x_gap_ratio

    rails: List[List[Span]] = []
    current: List[Span] = []
    last_x: float | None = None

    for s in xs:
        cx = (s["bbox"][0] + s["bbox"][2]) / 2
        if last_x is None:
            current = [s]
            last_x = cx
            continue

        if abs(cx - last_x) > x_gap:
            rails.append(current)
            current = [s]
        else:
            current.append(s)

        last_x = cx

    if current:
        rails.append(current)

    # 레일 내부에서는 y로만 정렬 (군집 유지)
    for r in rails:
        r.sort(key=lambda s: s["bbox"][1])

    return rails


def get_y_rails(
    spans: List[Dict[str, Any]], padding=1, min_count: int = 10
) -> List[float]:
    """페이지 분할을 위해 세로 기준선을 계산하여 반환한다
    Args:
        spans (List[Dict]): 페이지 전체 spans
        padding (float): 기준선 padding
        min_count (int): 기준선을 이루는 최소 span 갯수 설정
    Returns:
        List[float]: 분할 기준선 목록
    """
    # 1. x0 값만 추출
    x0s = [round(span["bbox"][0]) - padding for span in spans]
    x1s = [round(span["bbox"][2]) + padding for span in spans]

    # 2. 빈도 계산
    cnt_x0 = Counter(x0s)
    cnt_x1 = Counter(x1s)

    # 3. 조건 만족하는 x0만 필터링 (등장한 만큼 유지)
    x0_res = [x0 for x0 in x0s if cnt_x0[x0] >= min_count]
    x1_res = [x1 for x1 in x1s if cnt_x1[x1] >= min_count]

    # 4. 튜플로 반환
    return sorted(list(set(x0_res + x1_res)))
