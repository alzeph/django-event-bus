from django.db import models

from django_event_bus.remote import RemoteForeignKey


class Order(models.Model):
    user_id = RemoteForeignKey(
        service="service_auth",
        resource="users",
        invalidate_on=["auth.user_updated"],
    )
