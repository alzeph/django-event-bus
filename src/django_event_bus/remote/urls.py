"""URLs à inclure une fois pour exposer toutes les ressources déclarées.

    # service_auth/urls.py
    from django.urls import include, path
    urlpatterns = [path("api/", include("django_event_bus.remote.urls"))]

Quel que soit le nombre de ressources ``@expose_resource``, cette seule
ligne suffit — aucune vue à ajouter par ressource.

URLs to include once to expose every declared resource.

    # service_auth/urls.py
    from django.urls import include, path
    urlpatterns = [path("api/", include("django_event_bus.remote.urls"))]

Whatever the number of ``@expose_resource`` resources, this single line
is enough — no view to add per resource.
"""

from __future__ import annotations

from django.urls import path

from .views import resource_detail

app_name = "django_event_bus_remote"

urlpatterns = [
    path("<str:resource>/<str:pk>/", resource_detail, name="resource-detail"),
]
