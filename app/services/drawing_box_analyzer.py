from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Literal
import fitz  # PyMuPDF


BBox = Tuple[float, float, float, float]
Span = Dict[str, Any]
OutItem = Dict[str, Any]


def extract_texts_in_drawing_boxes(
    drawings: List[Dict[str, Any]],
    spans: List[Span],
    *,
    pad: float = 0.5,
    overlap_ratio: float = 0.85,
    min_span_len: int = 1,
    min_drawing_area: float = 20.0,
    sort_spans: bool = True,
    join_spans: bool = True,
    line_break_y: float = 2.0,
    word_gap_x: float = 1.5,
    # =========================
    # 중복/노이즈 방지
    # =========================
    rect_dedup_tol: float = 1.0,
    unique_assign: bool = True,
    assign_metric: Literal["contain", "iou"] = "contain",
    min_assign_score: float = 0.0,
    use_rect_nms: bool = False,
    rect_nms_iou: float = 0.9,
) -> List[OutItem]:
    """
    ✅ "이미 잘라진 페이지" 기준으로 drawings/spans가 같은 좌표계라고 가정하고 매칭한다.

    반환:
      join_spans=True  => rect 1개당 {"text": "...", "bbox": rect_bbox}
      join_spans=False => 포함된 span마다 {"text": "...", "bbox": span_bbox}
    """

    # 1) span 전처리
    cleaned_spans: List[Span] = []
    for sp in spans:
        text = (sp.get("text") or "").strip()
        if len(text) < min_span_len:
            continue
        bbox = sp.get("bbox")
        if not bbox or len(bbox) != 4:
            continue
        cleaned_spans.append({**sp, "text": text, "bbox": tuple(bbox)})

    if not cleaned_spans:
        return []

    # 2) drawing -> rect + pad + 면적 필터
    drawing_rects: List[fitz.Rect] = []
    for d in drawings:
        rect = _drawing_to_rect(d)
        if rect is None:
            continue

        rect = fitz.Rect(rect.x0 - pad, rect.y0 - pad, rect.x1 + pad, rect.y1 + pad)

        if rect.get_area() < min_drawing_area:
            continue

        drawing_rects.append(rect)

    if not drawing_rects:
        return []

    # 3) rect dedup / NMS
    drawing_rects = _dedup_rects(drawing_rects, tol=rect_dedup_tol)

    if use_rect_nms:
        drawing_rects = _rect_nms(drawing_rects, iou_thr=rect_nms_iou)

    if not drawing_rects:
        return []

    # 4) span 배정(중복 방지)
    if unique_assign:
        buckets = _assign_spans_to_best_rects(
            drawing_rects,
            cleaned_spans,
            overlap_ratio=overlap_ratio,
            metric=assign_metric,
            min_score=min_assign_score,
        )
    else:
        buckets: List[List[Span]] = []
        for rect in drawing_rects:
            picked: List[Span] = []
            for sp in cleaned_spans:
                sp_rect = fitz.Rect(sp["bbox"])
                if _overlap_enough(sp_rect, rect, overlap_ratio=overlap_ratio):
                    picked.append(sp)
            buckets.append(picked)

    # 5) 결과 구성
    results: List[OutItem] = []
    for rect, picked in zip(drawing_rects, buckets):
        if not picked:
            continue

        if sort_spans:
            picked.sort(key=lambda s: (_roundy(s["bbox"][1]), s["bbox"][0]))

        if join_spans:
            joined = _join_spans_simple(
                picked,
                line_break_y=line_break_y,
                word_gap_x=word_gap_x,
            ).strip()
            if not joined:
                continue
            results.append(
                {"text": joined, "bbox": (rect.x0, rect.y0, rect.x1, rect.y1)}
            )
        else:
            for sp in picked:
                results.append({"text": sp["text"], "bbox": tuple(sp["bbox"])})

    return results


def _drawing_to_rect(d: Dict[str, Any]) -> Optional[fitz.Rect]:
    # 가장 흔한 케이스
    if "rect" in d and d["rect"]:
        try:
            return fitz.Rect(d["rect"])
        except Exception:
            pass
    if "bbox" in d and d["bbox"]:
        try:
            return fitz.Rect(d["bbox"])
        except Exception:
            pass

    # items에서 유도
    items = d.get("items") or []
    points: List[Tuple[float, float]] = []

    for it in items:
        if not it:
            continue

        op = it[0]
        if op == "re" and len(it) >= 2:
            try:
                return fitz.Rect(it[1])
            except Exception:
                continue

        for part in it[1:]:
            if (
                isinstance(part, (list, tuple))
                and len(part) == 2
                and all(isinstance(v, (int, float)) for v in part)
            ):
                points.append((float(part[0]), float(part[1])))

    if not points:
        return None

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return fitz.Rect(min(xs), min(ys), max(xs), max(ys))


def _overlap_enough(a: fitz.Rect, b: fitz.Rect, *, overlap_ratio: float) -> bool:
    inter = a & b
    if inter.is_empty:
        return False
    a_area = max(a.get_area(), 1e-9)
    return (inter.get_area() / a_area) >= overlap_ratio


def _assign_spans_to_best_rects(
    rects: List[fitz.Rect],
    spans: List[Span],
    *,
    overlap_ratio: float,
    metric: Literal["contain", "iou"],
    min_score: float,
) -> List[List[Span]]:
    buckets: List[List[Span]] = [[] for _ in rects]

    for sp in spans:
        sp_rect = fitz.Rect(sp["bbox"])
        sp_area = max(sp_rect.get_area(), 1e-9)

        best_i: Optional[int] = None
        best_score = 0.0

        for i, r in enumerate(rects):
            inter = sp_rect & r
            if inter.is_empty:
                continue

            inter_area = inter.get_area()
            contain = inter_area / sp_area

            if contain < overlap_ratio:
                continue

            if metric == "iou":
                union = sp_area + r.get_area() - inter_area
                score = inter_area / max(union, 1e-9)
            else:
                score = contain

            if score > best_score:
                best_score = score
                best_i = i

        if best_i is not None and best_score >= min_score:
            buckets[best_i].append(sp)

    return buckets


def _dedup_rects(rects: List[fitz.Rect], *, tol: float = 1.0) -> List[fitz.Rect]:
    seen = set()
    out: List[fitz.Rect] = []
    for r in rects:
        key = (
            round(r.x0 / tol),
            round(r.y0 / tol),
            round(r.x1 / tol),
            round(r.y1 / tol),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _rect_iou(a: fitz.Rect, b: fitz.Rect) -> float:
    inter = a & b
    if inter.is_empty:
        return 0.0
    inter_area = inter.get_area()
    union = a.get_area() + b.get_area() - inter_area
    return inter_area / max(union, 1e-9)


def _rect_nms(rects: List[fitz.Rect], *, iou_thr: float = 0.9) -> List[fitz.Rect]:
    rects_sorted = sorted(rects, key=lambda r: r.get_area(), reverse=True)
    kept: List[fitz.Rect] = []

    for r in rects_sorted:
        if any(_rect_iou(r, k) >= iou_thr for k in kept):
            continue
        kept.append(r)

    return kept


def _join_spans_simple(
    spans: List[Span],
    *,
    line_break_y: float,
    word_gap_x: float,
) -> str:
    if not spans:
        return ""

    out: List[str] = []
    prev_bbox: Optional[BBox] = None

    for sp in spans:
        txt = sp["text"]
        bbox = tuple(sp["bbox"])

        if prev_bbox is None:
            out.append(txt)
            prev_bbox = bbox
            continue

        prev_x0, prev_y0, prev_x1, prev_y1 = prev_bbox
        x0, y0, x1, y1 = bbox

        if abs(y0 - prev_y0) > line_break_y:
            out.append("\n" + txt)
        else:
            if (x0 - prev_x1) > word_gap_x:
                out.append(" " + txt)
            else:
                out.append(txt)

        prev_bbox = bbox

    return "".join(out).strip()


def _roundy(y: float, base: float = 0.5) -> float:
    return round(y / base) * base
