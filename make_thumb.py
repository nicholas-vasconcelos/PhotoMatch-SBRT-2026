from pathlib import Path
from PIL import Image


# Change these values to control the generated thumbnail size.
THUMBNAIL_WIDTH = 320
THUMBNAIL_HEIGHT = 180
SOURCE_FOLDER = Path(".")
OUTPUT_FOLDER = Path("thumb")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def create_thumbnails() -> None:
	"""Create thumbnails while preserving the source folder structure."""
	for source in SOURCE_FOLDER.rglob("*"):
		if not source.is_file() or source.suffix.lower() not in IMAGE_EXTENSIONS:
			continue
		if OUTPUT_FOLDER in source.parents:
			continue

		destination = OUTPUT_FOLDER / source.relative_to(SOURCE_FOLDER)
		destination.parent.mkdir(parents=True, exist_ok=True)

		try:
			with Image.open(source) as image:
				image.thumbnail((THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT), Image.Resampling.LANCZOS)
				image.convert("RGB").save(destination.with_suffix(".jpg"), quality=90)
		except (OSError, ValueError) as error:
			print(f"Skipping {source}: {error}")


if __name__ == "__main__":
	create_thumbnails()
