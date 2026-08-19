"""Transport HTTP: convention REST ``GET {base_url}/{resource}/{pk}/``.

HTTP transport: REST convention ``GET {base_url}/{resource}/{pk}/``.
"""

from __future__ import annotations

from typing import Any

import requests

from ...exceptions import RemoteServiceUnavailableError
from .base import BaseTransport
from .utils import registry_entry


class HTTPTransport(BaseTransport):
    """Récupère une ressource distante par une requête HTTP GET conventionnelle.

    Le service source doit exposer ``GET {base_url}/{resource}/{pk}/``
    renvoyant un objet JSON représentant la ressource. Aucune bibliothèque
    REST particulière n'est requise côté service source (une simple vue
    Django suffit). La config par service (``base_url``, ``timeout``,
    ``headers`` optionnels) vient de
    ``REMOTE_DATA["SERVICE_REGISTRY"][service]["http"]``.

    Fetches a remote resource via a conventional HTTP GET request.

    The source service must expose ``GET {base_url}/{resource}/{pk}/``
    returning a JSON object representing the resource. No particular REST
    framework is required on the source service side (a plain Django view
    is enough). Per-service config (``base_url``, optional ``timeout``,
    ``headers``) comes from
    ``REMOTE_DATA["SERVICE_REGISTRY"][service]["http"]``.
    """

    def fetch(self, *, service: str, resource: str, pk: Any) -> dict[str, Any] | None:
        """Effectue le GET et renvoie le JSON décodé, ``None`` sur 404.

        Performs the GET and returns the decoded JSON, ``None`` on 404.
        """
        config = registry_entry(service, "http")
        base_url = str(config["base_url"]).rstrip("/")
        url = f"{base_url}/{resource}/{pk}/"

        try:
            response = requests.get(
                url,
                timeout=config.get("timeout", 3),
                headers=config.get("headers"),
            )
        except requests.RequestException as exc:
            raise RemoteServiceUnavailableError(
                f"Requête HTTP vers '{service}' ({url}) impossible / failed: {exc}"
            ) from exc

        if response.status_code == 404:
            return None
        if not response.ok:
            raise RemoteServiceUnavailableError(
                f"'{service}' a répondu {response.status_code} pour {url} / "
                f"responded {response.status_code} for {url}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise RemoteServiceUnavailableError(
                f"'{service}' a répondu un JSON invalide pour {url} / "
                f"responded invalid JSON for {url}: {exc}"
            ) from exc

    def close(self) -> None:
        """Rien à libérer: ``requests`` gère son propre pool de connexions.

        Nothing to release: ``requests`` manages its own connection pool.
        """
