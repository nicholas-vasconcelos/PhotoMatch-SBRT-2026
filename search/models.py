from django.db import models
from pgvector.django import VectorField


class FaceEmbedding(models.Model):
    image_name = models.CharField(max_length=512)
    day = models.CharField(max_length=64)
    face_index = models.IntegerField()
    bbox = models.JSONField()
    embedding = VectorField(dimensions=128)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["image_name", "face_index"], name="uniq_image_face_index"),
        ]
        indexes = [
            models.Index(fields=["image_name"]),
            models.Index(fields=["day"]),
        ]

    def __str__(self) -> str:
        return f"{self.image_name}#{self.face_index}"
