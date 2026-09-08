"""
Download face detection / recognition ONNX weights into the Triton model repository.

    python scripts/download_models.py            # fetch everything that is missing
    python scripts/download_models.py scrfd_10g  # fetch a subset

Idempotent: a model whose file already matches its pinned SHA256 is skipped, so this
is safe to re-run and safe to call from CI. Weights are gitignored; only the
config.pbtxt files next to them are tracked.

Every entry is pinned by SHA256 of the final model.onnx. If a checksum ever fails,
that means upstream re-published the artifact under the same URL -- do not "fix" it
by pasting in the new digest until you know what changed.
"""

import hashlib
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

MODEL_REPO = Path(__file__).resolve().parent.parent / "app" / "triton_server" / "models"
CACHE_DIR = Path(__file__).resolve().parent.parent / "app" / ".model_cache"

BUFFALO_L = "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip"


@dataclass(frozen=True)
class Model:
    """One Triton model: where its weights come from and what they must hash to."""

    url: str
    sha256: str  # digest of the extracted model.onnx, not of the archive
    zip_member: str | None = None
    note: str = ""


MODELS: dict[str, Model] = {
    # ---- detectors (all three emit 5 facial landmarks, which alignment requires) ----
    "scrfd_10g": Model(
        url=BUFFALO_L,
        zip_member="det_10g.onnx",
        sha256="5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91",
        note="InsightFace SCRFD-10GF, 9 outputs = 3 strides x (score, bbox, kps)",
    ),
    "yunet": Model(
        url="https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        sha256="8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
        note="OpenCV Zoo YuNet 2023mar, 12 outputs = 3 strides x (cls, obj, bbox, kps)",
    ),
    "yolo11n_face_5kp": Model(
        url="https://huggingface.co/huygiatrng/yolov11n-face-pose-5kp/resolve/main/face_5kp_yolo11n.onnx",
        sha256="27ef93e9ccc9e1f49ecdb29d443d1b986c31c8e69230e19584e888fcec86984f",
        note="YOLO11n-pose with 5 keypoints. NOT akanametov/yolo-face: that one outputs "
        "[1,5,8400] (bbox+conf only) and cannot drive landmark alignment.",
    ),
    # ---- recognizers (all 512-d, all 112x112 RGB) ----
    "arcface_r50": Model(
        url=BUFFALO_L,
        zip_member="w600k_r50.onnx",
        sha256="4c06341c33c2ca1f86781dab0e829f88ad5b64be9fba56e56bc9ebdefc619e43",
        note="InsightFace ArcFace R50 trained on WebFace600K",
    ),
    "auraface_glintr100": Model(
        url="https://huggingface.co/fal/AuraFace-v1/resolve/main/glintr100.onnx",
        sha256="a7933ea5330113b01c9b60351d8f4c33003f145d8470ac5f0e52ee2effe25c60",
        note="fal AuraFace-v1, glintr100 architecture",
    ),
    "lvface_b": Model(
        url="https://huggingface.co/bytedance-research/LVFace/resolve/main/LVFace-B_Glint360K/LVFace-B_Glint360K.onnx",
        sha256="9d834ed8e927fd35b9123b2bf97c40aad05785b1f9ecfb1c4c1f6242d38d1382",
        note="ByteDance LVFace-B trained on Glint360K (opset 17)",
    ),
}


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fptr:
        for chunk in iter(lambda: fptr.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, dest: Path) -> Path:
    """Fetch `url` into `dest`, reusing an existing download when present."""
    if dest.exists():
        print(f"    reusing cached {dest.name}")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"    GET {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as response, open(tmp, "wb") as out:  # noqa: S310
        total = int(response.headers.get("Content-Length") or 0)
        read = 0
        while chunk := response.read(1024 * 256):
            out.write(chunk)
            read += len(chunk)
            if total:
                print(f"\r    {100 * read // total:3d}%  {read >> 20:>4d}/{total >> 20} MiB", end="")
        print()
    tmp.rename(dest)
    return dest


def fetch(name: str, model: Model) -> bool:
    """Place `name`'s weights in the model repo. Returns True if anything was written."""
    target = MODEL_REPO / name / "1" / "model.onnx"
    if target.exists() and sha256_of(target) == model.sha256:
        print(f"[ok]   {name}: already present and verified")
        return False

    print(f"[get]  {name}: {model.note}")
    archive = download(model.url, CACHE_DIR / Path(model.url.split("?")[0]).name)

    with tempfile.TemporaryDirectory() as tmpdir:
        if model.zip_member:
            with zipfile.ZipFile(archive) as zfp:
                # zip entries may be nested (e.g. "buffalo_l/det_10g.onnx")
                member = next(n for n in zfp.namelist() if Path(n).name == model.zip_member)
                zfp.extract(member, tmpdir)
            source = Path(tmpdir) / member
        else:
            source = archive

        actual = sha256_of(source)
        if actual != model.sha256:
            raise SystemExit(
                f"checksum mismatch for {name}\n  expected {model.sha256}\n  actual   {actual}\n"
                f"  source   {model.url}\nUpstream changed the artifact; investigate before updating the pin."
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    print(f"[done] {name}: {target.relative_to(MODEL_REPO.parent.parent.parent)}")
    return True


def main(argv: list[str]) -> int:
    wanted = argv or list(MODELS)
    if unknown := [n for n in wanted if n not in MODELS]:
        raise SystemExit(f"unknown model(s): {', '.join(unknown)}\navailable: {', '.join(MODELS)}")

    for name in wanted:
        fetch(name, MODELS[name])

    print(f"\nModel repository: {MODEL_REPO}")
    print(f"Download cache:   {CACHE_DIR}  (safe to delete)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
