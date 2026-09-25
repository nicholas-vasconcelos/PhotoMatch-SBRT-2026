from __future__ import annotations

import os
from functools import lru_cache

from pgvector.django import L2Distance

from .models import FaceEmbedding
from .runtime import local_photo_db_path, should_use_local_photo_db


def get_match_threshold() -> float:
    return float(os.getenv("MATCH_THRESHOLD", "0.60"))


@lru_cache(maxsize=1)
def _load_local_photo_database() -> list[dict]:
    import face_engine as fe

    return fe.load_database(local_photo_db_path())


def _query_local_matches(query_embedding, threshold: float) -> list[dict]:
    import face_engine as fe

    matches = fe.search(query_embedding, _load_local_photo_database(), threshold=threshold)
    return [
        {
            "image_name": row["image_name"],
            "day": row.get("day", ""),
            "face_index": int(row["face_index"]),
            "bbox": row["bbox"],
            "distance": float(row["distance"]),
        }
        for row in matches
    ]


def query_vector_matches(query_embedding, threshold: float | None = None) -> list[dict]:
    resolved_threshold = get_match_threshold() if threshold is None else threshold

    if should_use_local_photo_db():
        return _query_local_matches(query_embedding, threshold=resolved_threshold)

    query_vector = query_embedding.tolist()

    queryset = (
        FaceEmbedding.objects.annotate(distance=L2Distance("embedding", query_vector))
        .filter(distance__lte=resolved_threshold)
        .order_by("distance")
        .values("image_name", "day", "face_index", "bbox", "distance")
    )

    return [
        {
            "image_name": row["image_name"],
            "day": row["day"],
            "face_index": row["face_index"],
            "bbox": row["bbox"],
            "distance": float(row["distance"]),
        }
        for row in queryset
    ]
