from __future__ import annotations

import os
from pathlib import Path


def _normalized_prefix(prefix: str) -> str:
    cleaned = (prefix or "").strip().strip("/")
    return f"{cleaned}/" if cleaned else ""


def _bucket_name() -> str:
    return os.getenv("S3_BUCKET", "").strip()


def _image_prefix() -> str:
    return os.getenv("S3_IMAGE_PREFIX", "dataset/").strip()


def build_presigned_get_url(image_name: str, expires_seconds: int = 300) -> str | None:
    bucket = _bucket_name()
    if not bucket:
        return None

    import boto3

    safe_name = Path(image_name).name
    key = f"{_normalized_prefix(_image_prefix())}{safe_name}"
    s3_client = boto3.client("s3")
    return s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires_seconds,
    )
