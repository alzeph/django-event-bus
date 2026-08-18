from accounts.views import get_user
from django.urls import path

urlpatterns = [
    path("api/users/<int:pk>/", get_user, name="api-user-detail"),
]
