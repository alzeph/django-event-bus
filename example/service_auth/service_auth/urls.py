from accounts.views import account_dashboard, account_list
from django.urls import include, path

urlpatterns = [
    # Un seul include, quel que soit le nombre de ressources exposées
    # via @expose_resource (voir accounts/resources.py) — sert
    # "GET /api/<resource>/<pk>/" pour toutes.
    path("api/", include("django_event_bus.remote.urls")),
    # Vues consultables au navigateur, voir accounts/views.py.
    path("accounts/", account_list, name="account-list"),
    path("accounts/<int:pk>/dashboard/", account_dashboard, name="account-dashboard"),
]
