# Face models

## Download

```bash
cd face_reg_recog_milvus
python3 scripts/download_models.py            # everything that is missing
python3 scripts/download_models.py scrfd_10g  # one model
```

The script writes into `app/triton_server/models/<name>/1/model.onnx`, which Docker
Compose mounts into Triton. The weights are not tracked by Git.

Each file is pinned by a SHA256 checksum. The script stops if a checksum does not
match. Do not replace the recorded checksum until you know why the file changed.

Downloads are cached in `app/.model_cache`, so a repeated run costs nothing. You can
delete that directory at any time.

## Available models

Detectors. All three report five facial landmarks, which alignment needs. A detector
that reports only a box cannot be used here.

| Name | Source | Notes |
| --- | --- | --- |
| `scrfd_10g` | InsightFace buffalo_l | Default. Accurate. |
| `yunet` | OpenCV Zoo | Very small, about 230 KB |
| `yolo11n_face_5kp` | YOLO11n pose, 5 keypoints | Fast |

Recognisers. All produce 512 values from a 112x112 image.

| Name | Source | Notes |
| --- | --- | --- |
| `arcface_r50` | InsightFace, WebFace600K | Default |
| `auraface_glintr100` | AuraFace v1 | |
| `lvface_b` | LVFace-B, Glint360K | Largest file |

## Change the active models

Set these in `.env`, then restart the API container.

```bash
FACE_DETECTOR=yunet
FACE_RECOGNIZER=lvface_b
```

```bash
docker compose up -d api
```

Triton loads every model in the repository at start. Only the pair you name is used.

### Changing the recogniser changes the collection

The Milvus collection name is built from the recogniser name, for example
`faces_arcface_r50`.

Two recognisers give vectors of the same length. Those vectors are **not**
comparable. Each model learns its own space, so the distance between a vector from
one model and a vector from another has no meaning. Milvus would accept the
comparison and return a confident, wrong answer.

So a new recogniser starts with an empty collection. Every person must be registered
again before recognition can work. This is deliberate. A silent wrong answer is worse
than an empty result.

## Settings

| Variable | Default | Effect |
| --- | --- | --- |
| `FACE_DETECTOR` | `scrfd_10g` | Which detector runs |
| `FACE_RECOGNIZER` | `arcface_r50` | Which recogniser runs, and which collection is used |
| `FACE_DET_THRESHOLD` | `0.5` | Lowest detector confidence that counts as a face |
| `FACE_MATCH_THRESHOLD` | `0.4` | Lowest cosine similarity that counts as a match |
| `FACE_MIN_AREA_FRACTION` | `0.001` | Smallest face, as a part of the frame |

Raise `FACE_MATCH_THRESHOLD` to accept fewer wrong matches and reject more correct
ones. Lower it for the opposite. Measure with your own images before you change it.

## Why alignment matters

The pipeline is detect, then align, then embed.

Alignment warps the five landmarks onto a fixed template, so the recogniser always
receives the same pose. Without it the recogniser sees the tilt of the head as if it
were a different person.

Measured on one image, comparing it with a rotated copy of itself:

| Head tilt | With alignment | Cropped box only |
| --- | --- | --- |
| 10 degrees | 0.920 | 0.845 |
| 20 degrees | 0.923 | 0.693 |
| 30 degrees | 0.916 | 0.631 |

At 30 degrees the cropped box falls below a 0.4 threshold long before alignment does.
The same person would not be recognised.

## Add a model

1. Confirm the ONNX outputs. A detector must give five landmarks.
2. Add an entry to `MODELS` in `scripts/download_models.py`, with its SHA256.
3. Add its preprocessing to `DETECTOR_SPECS` or `RECOGNIZER_SPECS` in
   `app/services/faces.py`.
4. A detector also needs a decode function, because each family arranges its outputs
   differently.

Triton reads the ONNX metadata and builds its own configuration, so no `config.pbtxt`
is needed. Its default instance type uses a GPU when one is present, and the CPU when
one is not.
