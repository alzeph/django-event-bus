from django.urls import include, path
from orders.views import order_dashboard, order_list

urlpatterns = [
    # Sert GET /api/orders/<pk>/ pour service_auth (voir orders/resources.py).
    path("api/", include("django_event_bus.remote.urls")),
    # Vues consultables au navigateur, voir orders/views.py.
    path("orders/", order_list, name="order-list"),
    path("orders/<int:pk>/dashboard/", order_dashboard, name="order-dashboard"),
]
