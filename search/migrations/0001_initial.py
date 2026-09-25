from django.db import migrations, models
from pgvector.django import VectorExtension, VectorField


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        VectorExtension(),
        migrations.CreateModel(
            name="FaceEmbedding",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("image_name", models.CharField(max_length=512)),
                ("day", models.CharField(max_length=64)),
                ("face_index", models.IntegerField()),
                ("bbox", models.JSONField()),
                ("embedding", VectorField(dimensions=128)),
            ],
            options={
                "indexes": [
                    models.Index(fields=["image_name"], name="search_facee_image_n_65f5de_idx"),
                    models.Index(fields=["day"], name="search_facee_day_582d08_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=("image_name", "face_index"), name="uniq_image_face_index")
                ],
            },
        ),
    ]
