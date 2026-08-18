from django.http import Http404, HttpResponse

from django_event_bus.exceptions import RemoteServiceUnavailableError

from .models import Order


def order_dashboard(request, pk):
    """Rend la commande locale et l'utilisateur résolu à distance côté service_auth.

    Preuve visuelle du sens 1 (service_order lit service_auth): la
    seule chose que ce module connaît de l'utilisateur est
    `order.user_id` ; `order.user` fait le reste (cache, sinon HTTP/gRPC
    vers service_auth) — voir orders/models.py.
    """
    try:
        order = Order.objects.get(pk=pk)
    except Order.DoesNotExist:
        raise Http404 from None

    try:
        user = order.user
        user_html = (
            f"<li>id: {user.id}</li><li>username: {user.username}</li>"
            f"<li>email: {user.email}</li><li>full_name: {user.full_name}</li>"
            if user is not None
            else "<li><em>utilisateur introuvable côté service_auth</em></li>"
        )
    except RemoteServiceUnavailableError as exc:
        user_html = f"<li><em>service_auth injoignable: {exc}</em></li>"

    local_html = (
        f"<li>id: {order.id}</li><li>reference: {order.reference}</li>"
        f"<li>user_id: {order.user_id}</li>"
    )
    html = f"""
    <h1>Commande {order.reference}</h1>
    <h2>Données locales (service_order)</h2>
    <ul>{local_html}</ul>
    <h2>Utilisateur résolu à distance (service_auth)</h2>
    <ul>{user_html}</ul>
    """
    return HttpResponse(html)
