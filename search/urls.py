from django.urls import path

from .views import health_view, home_view, local_photo_preview_view


urlpatterns = [
    path("", home_view, name="home"),
    path("health", health_view, name="health"),
    path("photos/<path:image_name>", local_photo_preview_view, name="local_photo_preview"),
]
