"""
face_engine.py
--------------
Core face detection, embedding, and search logic.
Extracted from the IBM4563 Colab notebook.
Uses `face_recognition` (dlib wrapper) instead of raw dlib
to avoid native compile issues on Beanstalk.

Dependencies: face_recognition, opencv-python-headless, numpy, Pillow
"""

import io
import os
import pickle
import numpy as np
from pathlib import Path
from PIL import Image

import face_recognition  # pip install face_recognition
import cv2

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
MODELS_DIR = Path(os.getenv("MODELS_DIR", "/tmp/models"))
DB_PATH = Path(os.getenv("DB_PATH", "/tmp/face_database.pkl"))
DATASET_IMAGES_DIR = Path(os.getenv("DATASET_IMAGES_DIR", "/tmp/dataset"))
MODELS_DIR.mkdir(parents=True, exist_ok=True)
DATASET_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Database type
# ---------------------------------------------------------------------------
# Each entry: {"image_name": str, "face_index": int, "bbox": dict, "embedding": np.ndarray}
FaceDatabase = list[dict]

# ---------------------------------------------------------------------------
# S3 asset management
# ---------------------------------------------------------------------------

def download_database_from_s3(bucket: str, s3_key: str, local_path: Path = DB_PATH) -> Path:
    """Download face_database.pkl from S3 if not already cached locally."""
    import boto3
    if local_path.exists():
        return local_path
    print(f"[S3] Downloading database from s3://{bucket}/{s3_key} ...")
    s3 = boto3.client("s3")
    s3.download_file(bucket, s3_key, str(local_path))
    print(f"[S3] Saved to {local_path}")
    return local_path


def upload_database_to_s3(bucket: str, s3_key: str, local_path: Path = DB_PATH):
    """Upload face_database.pkl to S3."""
    import boto3
    print(f"[S3] Uploading database to s3://{bucket}/{s3_key} ...")
    s3 = boto3.client("s3")
    s3.upload_file(str(local_path), bucket, s3_key)
    print("[S3] Upload complete.")


def _normalize_s3_prefix(prefix: str) -> str:
    """Ensure optional S3 prefix uses trailing slash when provided."""
    cleaned = (prefix or "").strip().strip("/")
    return f"{cleaned}/" if cleaned else ""


def upload_images_to_s3(bucket: str, prefix: str = "dataset/", images_dir: Path = DATASET_IMAGES_DIR) -> int:
    """Upload cached dataset images from local storage to S3."""
    import boto3

    if not images_dir.exists():
        return 0

    normalized_prefix = _normalize_s3_prefix(prefix)
    s3 = boto3.client("s3")
    uploaded = 0

    for image_path in images_dir.iterdir():
        if not image_path.is_file():
            continue

        s3_key = f"{normalized_prefix}{image_path.name}"
        s3.upload_file(str(image_path), bucket, s3_key)
        uploaded += 1

    print(f"[S3] Uploaded {uploaded} dataset image(s) to s3://{bucket}/{normalized_prefix}")
    return uploaded


def download_image_from_s3(
    bucket: str,
    image_name: str,
    prefix: str = "dataset/",
    images_dir: Path = DATASET_IMAGES_DIR,
) -> bytes | None:
    """
    Download one dataset image from S3 and cache it locally.
    Returns image bytes, or None when the key does not exist.
    """
    from botocore.exceptions import ClientError
    import boto3

    safe_name = Path(image_name).name
    local_path = images_dir / safe_name
    if local_path.exists():
        return local_path.read_bytes()

    normalized_prefix = _normalize_s3_prefix(prefix)
    s3_key = f"{normalized_prefix}{safe_name}"
    s3 = boto3.client("s3")

    try:
        obj = s3.get_object(Bucket=bucket, Key=s3_key)
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code in {"NoSuchKey", "404", "NotFound"}:
            return None
        raise

    data = obj["Body"].read()
    images_dir.mkdir(parents=True, exist_ok=True)
    with open(local_path, "wb") as f:
        f.write(data)
    return data

# ---------------------------------------------------------------------------
# Image utilities
# ---------------------------------------------------------------------------

def load_image_rgb(source) -> np.ndarray:
    """
    Load an image as an RGB numpy array.
    `source` can be: a file path (str/Path), bytes, or a BytesIO object.
    """
    if isinstance(source, (str, Path)):
        img = Image.open(source).convert("RGB")
    elif isinstance(source, (bytes, bytearray)):
        img = Image.open(io.BytesIO(source)).convert("RGB")
    elif isinstance(source, io.BytesIO):
        img = Image.open(source).convert("RGB")
    else:
        img = Image.open(source).convert("RGB")
    return np.array(img)


def save_dataset_images(image_sources: list[dict], images_dir: Path = DATASET_IMAGES_DIR) -> int:
    """
    Persist uploaded dataset images locally for search-result previews.
    Expects items shaped like {"name": str, "data": bytes}.
    Returns the number of images written.
    """
    images_dir.mkdir(parents=True, exist_ok=True)
    saved = 0

    for source in image_sources:
        if not isinstance(source, dict):
            continue

        name = source.get("name")
        data = source.get("data")
        if not name or data is None:
            continue

        out_path = images_dir / Path(name).name
        with open(out_path, "wb") as f:
            f.write(data)
        saved += 1

    return saved


def get_image_path(image_name: str, images_dir: Path = DATASET_IMAGES_DIR) -> Path | None:
    """Return the local dataset image path if it exists."""
    image_path = images_dir / Path(image_name).name
    if image_path.exists():
        return image_path
    return None


def draw_bboxes(img_rgb: np.ndarray, bboxes: list[dict], color=(0, 255, 0), thickness=2) -> np.ndarray:
    """Draw bounding boxes on a copy of the image. Returns RGB array."""
    out = img_rgb.copy()
    for i, bbox in enumerate(bboxes):
        top, right, bottom, left = bbox["top"], bbox["right"], bbox["bottom"], bbox["left"]
        cv2.rectangle(out, (left, top), (right, bottom), color, thickness)
        cv2.putText(out, f"face_{i}", (left, max(20, top - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)
    return out


def rect_to_dict(top, right, bottom, left) -> dict:
    return {
        "top": int(top), "right": int(right),
        "bottom": int(bottom), "left": int(left),
        "width": int(right - left), "height": int(bottom - top),
    }

# ---------------------------------------------------------------------------
# Core face processing (face_recognition library)
# ---------------------------------------------------------------------------

def detect_faces(img_rgb: np.ndarray, upsample: int = 1) -> list[dict]:
    """
    Detect faces and return list of bbox dicts.
    face_recognition returns (top, right, bottom, left) tuples.
    """
    locations = face_recognition.face_locations(img_rgb, number_of_times_to_upsample=upsample)
    return [rect_to_dict(*loc) for loc in locations]


def compute_embeddings(img_rgb: np.ndarray, bboxes: list[dict]) -> list[np.ndarray]:
    """
    Compute 128-D face embeddings for the given bounding boxes.
    Returns a list of numpy arrays (one per face).
    """
    # face_recognition expects (top, right, bottom, left) tuples
    locations = [(b["top"], b["right"], b["bottom"], b["left"]) for b in bboxes]
    encodings = face_recognition.face_encodings(img_rgb, known_face_locations=locations)
    return [np.array(e, dtype=np.float32) for e in encodings]


def euclidean_distance(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(a - b))

# ---------------------------------------------------------------------------
# Database building
# ---------------------------------------------------------------------------

def build_database(image_sources: list, progress_callback=None) -> FaceDatabase:
    """
    Build a face database from a list of image sources.

    Each source can be:
      - a dict: {"name": str, "data": bytes}
      - a Path object

    Returns a list of face entry dicts.

    progress_callback(current, total, image_name) is called each iteration
    if provided (used for Streamlit progress bars).
    """
    database: FaceDatabase = []
    total = len(image_sources)

    for idx, source in enumerate(image_sources):
        if isinstance(source, dict):
            name = source["name"]
            img_rgb = load_image_rgb(source["data"])
        else:
            name = Path(source).name
            img_rgb = load_image_rgb(source)

        if progress_callback:
            progress_callback(idx + 1, total, name)

        try:
            bboxes = detect_faces(img_rgb)
            embeddings = compute_embeddings(img_rgb, bboxes)

            for face_idx, (bbox, embedding) in enumerate(zip(bboxes, embeddings)):
                database.append({
                    "image_name": name,
                    "face_index": face_idx,
                    "bbox": bbox,
                    "embedding": embedding,
                })
        except Exception as e:
            print(f"[WARN] Failed to process {name}: {e}")
            continue

    return database


def save_database(database: FaceDatabase, path: Path = DB_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(database, f)
    print(f"[DB] Saved {len(database)} face entries to {path}")


def load_database(path: Path = DB_PATH) -> FaceDatabase:
    with open(path, "rb") as f:
        return pickle.load(f)

# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search(query_embedding: np.ndarray, database: FaceDatabase, threshold: float = 0.60) -> list[dict]:
    """
    Search the database for faces matching the query embedding.
    Returns a list of match dicts sorted by distance ascending.
    """
    results = []
    for entry in database:
        dist = euclidean_distance(query_embedding, entry["embedding"])
        if dist <= threshold:
            results.append({**entry, "distance": dist})
    return sorted(results, key=lambda x: x["distance"])


def get_query_embedding(img_rgb: np.ndarray) -> tuple[np.ndarray | None, list[dict]]:
    """
    Detect faces in a query image and return the embedding of the
    largest face, plus all detected bboxes for visualization.
    Returns (embedding, bboxes). embedding is None if no face found.
    """
    bboxes = detect_faces(img_rgb)
    if not bboxes:
        return None, []

    # Pick the largest face
    bboxes_sorted = sorted(bboxes, key=lambda b: b["width"] * b["height"], reverse=True)
    largest = bboxes_sorted[0]
    embeddings = compute_embeddings(img_rgb, [largest])
    if not embeddings:
        return None, bboxes_sorted

    return embeddings[0], bboxes_sorted
