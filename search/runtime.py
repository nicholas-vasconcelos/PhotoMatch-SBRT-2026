from __future__ import annotations

import os
from pathlib import Path

from django.conf import settings


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def is_running_on_aws() -> bool:
    return any(
        os.getenv(name)
        for name in (
            "AWS_EXECUTION_ENV",
            "ELASTIC_BEANSTALK_ENVIRONMENT_NAME",
            "ECS_CONTAINER_METADATA_URI",
            "ECS_CONTAINER_METADATA_URI_V4",
        )
    )


def local_photo_db_path() -> Path:
    configured = os.getenv("LOCAL_PHOTO_DB_PATH")
    if configured:
        return Path(configured).expanduser()
    return Path(settings.BASE_DIR) / "THF_face_database.pkl"


def local_photo_images_dir() -> Path:
    configured = os.getenv("LOCAL_PHOTO_IMAGES_DIR") or os.getenv("DATASET_IMAGES_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path(settings.BASE_DIR) / "dataset_images"


def should_use_local_photo_db() -> bool:
    return (
        _env_flag("LOCAL_PHOTO_DB_ENABLED", True)
        and not is_running_on_aws()
        and local_photo_db_path().exists()
    )
