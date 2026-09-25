from __future__ import annotations

import mimetypes
import os
from collections import defaultdict
from pathlib import Path

from django.http import FileResponse
from django.http import Http404
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse

from .forms import QueryUploadForm
from .runtime import is_running_on_aws
from .runtime import local_photo_images_dir
from .runtime import should_use_local_photo_db
from .s3 import build_presigned_get_url
from .services import query_vector_matches


def _build_preview_url(image_name: str) -> str | None:
    s3_url = build_presigned_get_url(image_name)
    if s3_url:
        return s3_url

    if should_use_local_photo_db():
        safe_name = Path(image_name).name
        return reverse("local_photo_preview", kwargs={"image_name": safe_name})

    return None


def _aggregate_matches(matches: list[dict]) -> list[dict]:
    by_image: dict[str, dict] = {}
    counts: dict[str, int] = defaultdict(int)
    for match in matches:
        image_name = match["image_name"]
        counts[image_name] += 1
        current = by_image.get(image_name)
        if current is None or match["distance"] < current["best_distance"]:
            by_image[image_name] = {
                "image_name": image_name,
                "best_distance": float(match["distance"]),
            }

    return sorted(
        [
            {
                "image_name": item["image_name"],
                "best_distance": item["best_distance"],
                "matching_faces": counts[item["image_name"]],
                "preview_url": _build_preview_url(item["image_name"]),
            }
            for item in by_image.values()
        ],
        key=lambda x: x["best_distance"],
    )


def home_view(request):
    context: dict = {
        "form": QueryUploadForm(),
        "results": [],
        "has_query": False,
        "no_match_message": "",
        "error_message": "",
    }

    if request.method != "POST":
        return render(request, "search/home.html", context)

    form = QueryUploadForm(request.POST, request.FILES)
    context["form"] = form
    context["has_query"] = True

    if not form.is_valid():
        context["error_message"] = form.errors.get("__all__", ["Invalid form data."])[0]
        return render(request, "search/home.html", context, status=400)

    uploaded = form.cleaned_data.get("selfie_capture") or form.cleaned_data.get("selfie_file")
    try:
        import face_engine as fe
    except ModuleNotFoundError as exc:
        if exc.name in {"pkg_resources", "face_recognition_models"}:
            context["error_message"] = (
                "Face search dependencies are missing. Install project requirements and restart the server."
            )
            return render(request, "search/home.html", context, status=500)
        raise
    except SystemExit:
        context["error_message"] = (
            "Face search dependencies are not available. Install project requirements and restart the server."
        )
        return render(request, "search/home.html", context, status=500)

    query_bytes = uploaded.read()
    query_img = fe.load_image_rgb(query_bytes)
    query_embedding, _query_bboxes = fe.get_query_embedding(query_img)

    if query_embedding is None:
        context["error_message"] = "No face detected in the uploaded photo. Please try another photo."
        return render(request, "search/home.html", context, status=422)

    threshold = float(os.getenv("MATCH_THRESHOLD", "0.60"))
    matches = query_vector_matches(query_embedding, threshold=threshold)
    if not matches:
        context["no_match_message"] = "No matching photos found — try another photo"
        return render(request, "search/home.html", context)

    context["results"] = _aggregate_matches(matches)
    return render(request, "search/home.html", context)


def health_view(_request):
    return JsonResponse({"status": "ok"}, status=200)


def local_photo_preview_view(_request, image_name: str):
    if is_running_on_aws():
        raise Http404("Not found")

    safe_name = Path(image_name).name
    photo_path = local_photo_images_dir() / safe_name
    if not photo_path.exists() or not photo_path.is_file():
        raise Http404("Photo not found")

    content_type, _encoding = mimetypes.guess_type(str(photo_path))
    return FileResponse(photo_path.open("rb"), content_type=content_type or "application/octet-stream")
