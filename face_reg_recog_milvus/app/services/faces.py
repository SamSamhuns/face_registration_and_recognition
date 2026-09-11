"""
Face detection, alignment and embedding.

    detect  -> bbox + 5 landmarks
    align   -> similarity-transform the landmarks onto a fixed template, warp to 112x112
    embed   -> 512-d, L2-normalised

The align step is what the previous implementation lacked entirely. It cropped the raw
bounding box out of an already-downscaled 448x448 letterboxed image and resized that.
ArcFace-family recognisers are trained on faces warped onto a canonical 5-point
template, so unaligned crops cost a large fraction of their accuracy.

All three detectors emit 5 landmarks, which is a hard requirement here -- a
bbox-only face detector cannot drive this pipeline.
"""

import logging
from dataclasses import dataclass

import cv2
import numpy as np

from app.services import triton

logger = logging.getLogger("faces")

# Canonical ArcFace 5-point template for a 112x112 crop, in
# (left eye, right eye, nose, left mouth corner, right mouth corner) order.
ARCFACE_TEMPLATE = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float32,
)
FACE_SIZE = 112


@dataclass
class Face:
    """One detected face in original-image pixel coordinates."""

    bbox: np.ndarray  # (4,) x1, y1, x2, y2
    score: float
    kps: np.ndarray  # (5, 2)

    def area_fraction(self, img_h: int, img_w: int) -> float:
        """Bounding box area as a fraction of the whole frame."""
        x1, y1, x2, y2 = self.bbox
        return float((x2 - x1) * (y2 - y1)) / float(img_h * img_w)


# --------------------------------------------------------------------------- preprocess

# mean/std are applied as (pixel - mean) / std. swap_rb converts the cv2 BGR read to RGB.
DETECTOR_SPECS = {
    "scrfd_10g": {"size": 640, "mean": 127.5, "std": 128.0, "swap_rb": True},
    "yunet": {"size": 640, "mean": 0.0, "std": 1.0, "swap_rb": False},
    "yolo11n_face_5kp": {"size": 640, "mean": 0.0, "std": 255.0, "swap_rb": True},
}
# every supported recogniser happens to share the insightface convention
RECOGNIZER_SPECS = {
    "arcface_r50": {"mean": 127.5, "std": 127.5, "swap_rb": True},
    "auraface_glintr100": {"mean": 127.5, "std": 127.5, "swap_rb": True},
    "lvface_b": {"mean": 127.5, "std": 127.5, "swap_rb": True},
}


def _to_blob(img: np.ndarray, mean: float, std: float, swap_rb: bool) -> np.ndarray:
    """HWC BGR uint8 image -> NCHW float32 batch of 1."""
    arr = img[:, :, ::-1] if swap_rb else img
    arr = (arr.astype(np.float32) - mean) / std
    return np.transpose(arr, (2, 0, 1))[None, ...]


def _letterbox(img: np.ndarray, size: int) -> tuple[np.ndarray, float]:
    """
    Resize preserving aspect ratio, padding right/bottom only.

    Padding one corner, and not the centre, means one divide by `scale` undoes it.
    Centred padding would need an offset for each axis as well.
    """
    img_h, img_w = img.shape[:2]
    scale = min(size / img_w, size / img_h)
    new_w, new_h = int(round(img_w * scale)), int(round(img_h * scale))
    canvas = np.zeros((size, size, 3), dtype=img.dtype)
    canvas[:new_h, :new_w] = cv2.resize(img, (new_w, new_h))
    return canvas, scale


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_thresh: float = 0.4) -> list[int]:
    """Greedy NMS via OpenCV (already a dependency) -- boxes are xyxy."""
    if len(boxes) == 0:
        return []
    wh = np.column_stack([boxes[:, 0], boxes[:, 1], boxes[:, 2] - boxes[:, 0], boxes[:, 3] - boxes[:, 1]])
    keep = cv2.dnn.NMSBoxes(wh.tolist(), scores.tolist(), score_threshold=0.0, nms_threshold=iou_thresh)
    return np.array(keep).flatten().tolist()


# ----------------------------------------------------------------------------- decoders


def _decode_scrfd(out: dict[str, np.ndarray], thresh: float, size: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    SCRFD emits 9 tensors: 3 strides x (score, bbox-distance, kps-distance).

    Output tensor names are raw graph node numbers ('448', '451', ...), so they are
    matched by shape instead: last dim 1/4/10 gives the kind, and the row count gives
    the stride, since rows = (size/stride)^2 * num_anchors.
    """
    by_stride: dict[int, dict[str, np.ndarray]] = {}
    for arr in out.values():
        arr = arr.reshape(arr.shape[-2], arr.shape[-1]) if arr.ndim == 3 else arr
        rows, last = arr.shape
        stride = int(round(size / np.sqrt(rows / 2)))  # 2 anchors per location
        kind = {1: "score", 4: "bbox", 10: "kps"}[last]
        by_stride.setdefault(stride, {})[kind] = arr

    boxes, scores, kpss = [], [], []
    for stride, group in sorted(by_stride.items()):
        score = group["score"].ravel()
        keep = score >= thresh
        if not keep.any():
            continue
        cells = size // stride
        # anchor centres: (x, y) per cell, repeated for the 2 anchors at each location
        grid = np.stack(np.meshgrid(np.arange(cells), np.arange(cells), indexing="ij")[::-1], axis=-1)
        centers = (grid.reshape(-1, 2) * stride).astype(np.float32).repeat(2, axis=0)[keep]

        dist = group["bbox"][keep] * stride
        boxes.append(np.column_stack([centers - dist[:, :2], centers + dist[:, 2:]]))

        kp = group["kps"][keep] * stride
        kpss.append(kp.reshape(-1, 5, 2) + centers[:, None, :])
        scores.append(score[keep])

    if not boxes:
        return np.empty((0, 4)), np.empty((0,)), np.empty((0, 5, 2))
    return np.vstack(boxes), np.concatenate(scores), np.vstack(kpss)


def _decode_yunet(out: dict[str, np.ndarray], thresh: float, size: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """YuNet emits cls/obj/bbox/kps per stride; confidence is sqrt(cls * obj)."""
    boxes, scores, kpss = [], [], []
    for stride in (8, 16, 32):
        cls = out[f"cls_{stride}"].reshape(-1)
        obj = out[f"obj_{stride}"].reshape(-1)
        bbox = out[f"bbox_{stride}"].reshape(-1, 4)
        kps = out[f"kps_{stride}"].reshape(-1, 10)

        score = np.sqrt(np.clip(cls, 0, 1) * np.clip(obj, 0, 1))
        keep = score >= thresh
        if not keep.any():
            continue
        cells = size // stride
        grid = np.stack(np.meshgrid(np.arange(cells), np.arange(cells), indexing="ij")[::-1], axis=-1)
        centers = grid.reshape(-1, 2).astype(np.float32)[keep]

        bbox = bbox[keep]
        cxcy = (centers + bbox[:, :2]) * stride
        wh = np.exp(bbox[:, 2:]) * stride
        boxes.append(np.column_stack([cxcy - wh / 2, cxcy + wh / 2]))

        kp = kps[keep].reshape(-1, 5, 2)
        kpss.append((centers[:, None, :] + kp) * stride)
        scores.append(score[keep])

    if not boxes:
        return np.empty((0, 4)), np.empty((0,)), np.empty((0, 5, 2))
    return np.vstack(boxes), np.concatenate(scores), np.vstack(kpss)


def _decode_yolo(out: dict[str, np.ndarray], thresh: float, size: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """YOLO11-pose: (1, 20, 8400) -> per candidate [cx, cy, w, h, conf, 5 x (x, y, vis)]."""
    pred = next(iter(out.values()))[0].T  # (8400, 20)
    score = pred[:, 4]
    keep = score >= thresh
    if not keep.any():
        return np.empty((0, 4)), np.empty((0,)), np.empty((0, 5, 2))
    pred = pred[keep]
    cxcy, wh = pred[:, :2], pred[:, 2:4]
    boxes = np.column_stack([cxcy - wh / 2, cxcy + wh / 2])
    kps = pred[:, 5:].reshape(-1, 5, 3)[:, :, :2]  # drop the visibility channel
    return boxes, score[keep], kps


_DECODERS = {"scrfd_10g": _decode_scrfd, "yunet": _decode_yunet, "yolo11n_face_5kp": _decode_yolo}


# ------------------------------------------------------------------------------- detect


def detect(img: np.ndarray, model: str, thresh: float = 0.5) -> list[Face]:
    """Detect faces in a BGR image. Coordinates come back in original-image pixels."""
    spec = DETECTOR_SPECS[model]
    size = spec["size"]
    canvas, scale = _letterbox(img, size)
    blob = _to_blob(canvas, spec["mean"], spec["std"], spec["swap_rb"])

    out = triton.infer(model, {triton.input_name(model): blob})
    boxes, scores, kpss = _DECODERS[model](out, thresh, size)
    if len(boxes) == 0:
        return []

    keep = _nms(boxes, scores)
    boxes, scores, kpss = boxes[keep], scores[keep], kpss[keep]

    # undo the letterbox: single divide, no offset, because padding was right/bottom only
    boxes /= scale
    kpss /= scale
    img_h, img_w = img.shape[:2]
    boxes[:, 0::2] = boxes[:, 0::2].clip(0, img_w)
    boxes[:, 1::2] = boxes[:, 1::2].clip(0, img_h)

    faces = [Face(bbox=b, score=float(s), kps=k) for b, s, k in zip(boxes, scores, kpss, strict=True)]
    faces.sort(key=lambda f: f.score, reverse=True)
    return faces


# -------------------------------------------------------------------------------- align


def _umeyama(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """
    Least-squares similarity transform (Umeyama 1991), returned as a 2x3 matrix.

    This is what insightface/skimage use for face alignment. cv2.estimateAffinePartial2D
    is *not* equivalent -- it robust-fits (RANSAC/LMEDS), which on exactly 5 exact
    correspondences gives a different answer than the least-squares solution the
    recognisers were trained against.
    """
    dim = src.shape[1]
    src_mean, dst_mean = src.mean(axis=0), dst.mean(axis=0)
    src_demean, dst_demean = src - src_mean, dst - dst_mean

    cov = dst_demean.T @ src_demean / src.shape[0]
    d = np.ones(dim)
    if np.linalg.det(cov) < 0:
        d[dim - 1] = -1

    u_mat, s_vals, vt_mat = np.linalg.svd(cov)
    rank = np.linalg.matrix_rank(cov)
    if rank == 0:
        raise ValueError("degenerate landmarks: cannot align")
    if rank == dim - 1 and np.linalg.det(u_mat) * np.linalg.det(vt_mat) < 0:
        d[dim - 1] = -1
    rotation = u_mat @ np.diag(d) @ vt_mat

    scale = (s_vals @ d) / src_demean.var(axis=0).sum()
    transform = np.eye(3)
    transform[:dim, :dim] = scale * rotation
    transform[:dim, dim] = dst_mean - scale * rotation @ src_mean
    return transform[:2].astype(np.float32)


def align(img: np.ndarray, kps: np.ndarray) -> np.ndarray:
    """Warp the face so its 5 landmarks land on the ArcFace template. Returns 112x112 BGR."""
    matrix = _umeyama(np.asarray(kps, dtype=np.float64), ARCFACE_TEMPLATE.astype(np.float64))
    return cv2.warpAffine(img, matrix, (FACE_SIZE, FACE_SIZE), borderValue=0.0)


# -------------------------------------------------------------------------------- embed


def embed(aligned: np.ndarray, model: str) -> np.ndarray:
    """Embed an aligned 112x112 BGR face. Returns a L2-normalised 512-d vector."""
    spec = RECOGNIZER_SPECS[model]
    blob = _to_blob(aligned, spec["mean"], spec["std"], spec["swap_rb"])
    out = triton.infer(model, {triton.input_name(model): blob})
    vec = next(iter(out.values())).reshape(-1).astype(np.float32)
    norm = np.linalg.norm(vec)
    # L2-normalise so that COSINE / inner-product search in Milvus is meaningful
    return vec / norm if norm > 0 else vec


# ----------------------------------------------------------------------------- pipeline


class FaceError(Exception):
    """A face-pipeline failure caused by the input image, not by the server."""


class NoFaceDetectedError(FaceError):
    pass


class TooManyFacesError(FaceError):
    pass


def embed_primary_face(
    img: np.ndarray,
    detector: str,
    recognizer: str,
    det_thresh: float = 0.5,
    min_area_fraction: float = 0.0,
    max_faces: int = 1,
) -> tuple[np.ndarray, Face]:
    """
    detect -> align -> embed, for the highest-scoring face in `img`.

    Raises NoFaceDetectedError / TooManyFacesError so the caller can map them onto distinct HTTP
    responses instead of collapsing every failure into one 400.
    """
    img_h, img_w = img.shape[:2]
    found = [f for f in detect(img, detector, det_thresh) if f.area_fraction(img_h, img_w) >= min_area_fraction]

    if not found:
        raise NoFaceDetectedError("no faces were detected in the image")
    if len(found) > max_faces:
        raise TooManyFacesError(f"detected {len(found)} faces, at most {max_faces} allowed")

    face = found[0]  # detect() returns highest-confidence first
    return embed(align(img, face.kps), recognizer), face


def read_image(path: str) -> np.ndarray:
    """Load a BGR image from disk, raising FaceError if it is not a decodable image."""
    img = cv2.imread(path)
    if img is None:
        raise FaceError("file could not be decoded as an image")
    return img
