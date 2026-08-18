from django.contrib.auth.models import User
from django.http import Http404, HttpResponse

from django_event_bus.exceptions import RemoteServiceUnavailableError

from .models import OrderBookmark


def account_dashboard(request, pk):
    """Rend l'utilisateur local et, si épinglée, la commande résolue côté service_order.

    Preuve visuelle du sens 2 (service_auth lit service_order): ce
    module ne connaît que `bookmark.order_id` ; `bookmark.order` fait le
    reste — voir accounts/models.py::OrderBookmark.
    """
    try:
        user = User.objects.get(pk=pk)
    except User.DoesNotExist:
        raise Http404 from None

    try:
        bookmark = user.order_bookmark
    except OrderBookmark.DoesNotExist:
        bookmark = None

    if bookmark is None:
        order_html = "<li><em>aucune commande épinglée</em></li>"
    else:
        try:
            order = bookmark.order
            order_html = (
                f"<li>id: {order.id}</li><li>reference: {order.reference}</li>"
                if order is not None
                else "<li><em>commande introuvable côté service_order</em></li>"
            )
        except RemoteServiceUnavailableError as exc:
            order_html = f"<li><em>service_order injoignable: {exc}</em></li>"

    html = f"""
    <h1>Compte {user.username}</h1>
    <h2>Données locales (service_auth)</h2>
    <ul><li>id: {user.id}</li><li>email: {user.email}</li></ul>
    <h2>Commande épinglée résolue à distance (service_order)</h2>
    <ul>{order_html}</ul>
    """
    return HttpResponse(html)
