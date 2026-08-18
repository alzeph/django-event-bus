from django.contrib.auth.models import User
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.urls import reverse

from django_event_bus.exceptions import RemoteServiceUnavailableError

from .models import OrderBookmark

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


def account_list(request):
    """Liste les comptes et permet d'en créer un nouveau."""
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip()
        if username:
            user = User.objects.create_user(
                username=username, email=email, password="demo"
            )
            return HttpResponseRedirect(reverse("account-dashboard", args=[user.id]))

    rows = "".join(
        f'<li><a href="{reverse("account-dashboard", args=[u.id])}">'
        f"#{u.id} {u.username} ({u.email})</a></li>"
        for u in User.objects.order_by("id")
    )
    body = f"""
    <h1>Comptes (service_auth)</h1>
    <p><a href="http://localhost:8002/orders/">Voir les commandes</a></p>
    <ul>{rows or "<li><em>aucun compte</em></li>"}</ul>
    <h2>Créer un compte</h2>
    <form method="post">
        <label>Username <input name="username" required></label>
        <label>Email <input name="email" type="email"></label>
        <button type="submit">Créer</button>
    </form>
    """
    return _page("Comptes", body)


def account_dashboard(request, pk):
    """Rend l'utilisateur local et la commande épinglée résolue côté service_order.

    Ce module ne connaît que `bookmark.order_id` ; `bookmark.order` fait
    la résolution à distance — voir accounts/models.py::OrderBookmark.
    Les deux formulaires ci-dessous déclenchent respectivement
    `auth.user_updated` (via post_save, voir events.py) et un simple set
    du bookmark local.
    """
    try:
        user = User.objects.get(pk=pk)
    except User.DoesNotExist:
        raise Http404 from None

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "update_email":
            user.email = request.POST.get("email", user.email)
            user.save()
        elif action == "set_bookmark":
            order_id = request.POST.get("order_id", "").strip()
            if order_id.isdigit():
                OrderBookmark.objects.update_or_create(
                    user=user, defaults={"order_id": int(order_id)}
                )
        return HttpResponseRedirect(reverse("account-dashboard", args=[pk]))

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

    bookmarked_order_id = bookmark.order_id if bookmark else ""
    account_list_url = reverse("account-list")
    body = f"""
    <p><a href="{account_list_url}">&larr; tous les comptes</a></p>
    <h1>Compte {user.username}</h1>
    <h2>Données locales (service_auth)</h2>
    <ul><li>id: {user.id}</li><li>email: {user.email}</li></ul>
    <form method="post">
        <input type="hidden" name="action" value="update_email">
        <label>Nouvel email
            <input name="email" type="email" value="{user.email}">
        </label>
        <button type="submit">Mettre à jour l'email</button>
    </form>
    <h2>Commande épinglée résolue à distance (service_order)</h2>
    <ul>{order_html}</ul>
    <form method="post">
        <input type="hidden" name="action" value="set_bookmark">
        <label>ID de commande à épingler
            <input name="order_id" value="{bookmarked_order_id}">
        </label>
        <button type="submit">Épingler</button>
    </form>
    """
    return _page(f"Compte {user.username}", body)
