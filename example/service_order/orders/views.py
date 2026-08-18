from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.urls import reverse

from django_event_bus.exceptions import RemoteServiceUnavailableError

from .models import Order

# Pas de CSRF ni de validation de formulaire (MIDDLEWARE=[] dans
# settings.py): ces vues sont une démo cliquable, pas du code de prod.
_STYLE = (
    "<style>body{font-family:sans-serif;max-width:640px;margin:2rem auto}"
    "input{display:block;margin:.25rem 0 .75rem;padding:.25rem}"
    "form{border:1px solid #ccc;padding:1rem;border-radius:4px}</style>"
)


def _page(title, body):
    head = f"<head><title>{title}</title>{_STYLE}</head>"
    return HttpResponse(f"<html>{head}<body>{body}</body></html>")


def order_list(request):
    """Liste les commandes et permet d'en créer une nouvelle."""
    if request.method == "POST":
        reference = request.POST.get("reference", "").strip()
        user_id = request.POST.get("user_id", "").strip()
        if reference and user_id.isdigit():
            order = Order.objects.create(reference=reference, user_id=int(user_id))
            return HttpResponseRedirect(reverse("order-dashboard", args=[order.id]))

    rows = "".join(
        f'<li><a href="{reverse("order-dashboard", args=[o.id])}">'
        f"#{o.id} {o.reference} (user_id={o.user_id})</a></li>"
        for o in Order.objects.order_by("id")
    )
    body = f"""
    <h1>Commandes (service_order)</h1>
    <p><a href="http://localhost:8001/accounts/">Voir les comptes</a></p>
    <ul>{rows or "<li><em>aucune commande</em></li>"}</ul>
    <h2>Créer une commande</h2>
    <form method="post">
        <label>Référence <input name="reference" required></label>
        <label>ID utilisateur (service_auth)
            <input name="user_id" type="number" required>
        </label>
        <button type="submit">Créer</button>
    </form>
    """
    return _page("Commandes", body)


def order_dashboard(request, pk):
    """Rend la commande locale et l'utilisateur résolu à distance côté service_auth.

    Preuve visuelle du sens 1 (service_order lit service_auth): la
    seule chose que ce module connaît de l'utilisateur est
    `order.user_id` ; `order.user` fait le reste (cache, sinon HTTP/gRPC
    vers service_auth) — voir orders/models.py. Le formulaire ci-dessous
    déclenche `orders.order_updated` (via post_save, voir events.py).
    """
    try:
        order = Order.objects.get(pk=pk)
    except Order.DoesNotExist:
        raise Http404 from None

    if request.method == "POST":
        order.reference = request.POST.get("reference", order.reference)
        order.save()
        return HttpResponseRedirect(reverse("order-dashboard", args=[pk]))

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
    order_list_url = reverse("order-list")
    body = f"""
    <p><a href="{order_list_url}">&larr; toutes les commandes</a></p>
    <h1>Commande {order.reference}</h1>
    <h2>Données locales (service_order)</h2>
    <ul>{local_html}</ul>
    <form method="post">
        <label>Nouvelle référence
            <input name="reference" value="{order.reference}">
        </label>
        <button type="submit">Mettre à jour</button>
    </form>
    <h2>Utilisateur résolu à distance (service_auth)</h2>
    <ul>{user_html}</ul>
    """
    return _page(f"Commande {order.reference}", body)
