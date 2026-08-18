from django.urls import include, path
from orders.views import order_dashboard

urlpatterns = [
    # Sert GET /api/orders/<pk>/ pour service_auth (voir orders/resources.py).
    path("api/", include("django_event_bus.remote.urls")),
    # Vue consultable au navigateur, voir orders/views.py.
    path("orders/<int:pk>/dashboard/", order_dashboard, name="order-dashboard"),
]
