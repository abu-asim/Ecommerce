"""
URL configuration for config project.
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView


urlpatterns = [
    path("admin/", admin.site.urls),

    # Homepage → Products
    path(
        "",
        RedirectView.as_view(
            url="/products/",
            permanent=False
        ),
        name="home",
    ),

    # Products
    path("products/", include("products.urls")),
]


# Media files
urlpatterns += static(
    settings.MEDIA_URL,
    document_root=settings.MEDIA_ROOT
)