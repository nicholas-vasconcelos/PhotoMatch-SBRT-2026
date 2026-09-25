from __future__ import annotations

import glob
import os
import pickle
from pathlib import Path

import numpy as np
from django.core.management.base import BaseCommand, CommandError

from search.models import FaceEmbedding


def _default_glob_pattern() -> str:
    configured = os.getenv("PKL_SHARD_GLOB", "").strip()
    if configured:
        return configured
    return str(Path(os.getenv("MODELS_DIR", "/tmp/models")) / "*.pkl")


def _infer_day(entry: dict, image_name: str) -> str:
    if entry.get("day"):
        return str(entry["day"])
    name = Path(image_name).stem
    day_candidate = name.split("_", 1)[0]
    return day_candidate if day_candidate else "unknown"


class Command(BaseCommand):
    help = "Import face embeddings from PKL shard files into FaceEmbedding table."

    def add_arguments(self, parser):
        parser.add_argument(
            "--glob",
            dest="glob_pattern",
            default=_default_glob_pattern(),
            help="Glob expression for PKL shards (default: env PKL_SHARD_GLOB or MODELS_DIR/*.pkl).",
        )
        parser.add_argument(
            "--batch-size",
            dest="batch_size",
            type=int,
            default=1000,
            help="Bulk insert batch size.",
        )

    def handle(self, *args, **options):
        glob_pattern = options["glob_pattern"]
        batch_size = options["batch_size"]
        shard_paths = sorted(glob.glob(glob_pattern))
        if not shard_paths:
            raise CommandError(f"No PKL shards found for pattern: {glob_pattern}")

        created_total = 0
        for shard in shard_paths:
            with open(shard, "rb") as fp:
                records = pickle.load(fp)

            if not isinstance(records, list):
                self.stderr.write(self.style.WARNING(f"Skipping non-list shard: {shard}"))
                continue

            objects = []
            for row in records:
                if not isinstance(row, dict):
                    continue

                image_name = str(row.get("image_name", "")).strip()
                if not image_name:
                    continue

                try:
                    face_index = int(row.get("face_index", 0))
                except (TypeError, ValueError):
                    continue

                embedding_raw = row.get("embedding")
                if embedding_raw is None:
                    continue

                embedding = np.asarray(embedding_raw, dtype=np.float32)
                if embedding.shape != (128,):
                    continue

                objects.append(
                    FaceEmbedding(
                        image_name=image_name,
                        day=_infer_day(row, image_name),
                        face_index=face_index,
                        bbox=row.get("bbox") or {},
                        embedding=embedding.tolist(),
                    )
                )

            if not objects:
                self.stdout.write(self.style.WARNING(f"No valid rows in shard: {shard}"))
                continue

            created = 0
            for start in range(0, len(objects), batch_size):
                chunk = objects[start : start + batch_size]
                inserted = FaceEmbedding.objects.bulk_create(
                    chunk,
                    batch_size=batch_size,
                    ignore_conflicts=True,
                )
                created += len(inserted)

            created_total += created
            self.stdout.write(f"{Path(shard).name}: inserted {created} row(s)")

        self.stdout.write(self.style.SUCCESS(f"Done. Inserted {created_total} row(s) total."))
