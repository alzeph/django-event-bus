"""Transport HTTP: convention REST ``GET {base_url}/{resource}/{pk}/``.

HTTP transport: REST convention ``GET {base_url}/{resource}/{pk}/``.
"""

from __future__ import annotations

import json
from typing import Any

import requests

from ...exceptions import RemoteServiceMisconfiguredError, RemoteServiceUnavailableError
from ...settings import remote_settings
from .base import BaseTransport
from .utils import registry_entry

_CHUNK_SIZE = 65_536


class HTTPTransport(BaseTransport):
    """Récupère une ressource distante par une requête HTTP GET conventionnelle.

    Le service source doit exposer ``GET {base_url}/{resource}/{pk}/``
    renvoyant un objet JSON représentant la ressource. Aucune bibliothèque
    REST particulière n'est requise côté service source (une simple vue
    Django suffit). La config par service (``base_url``, ``timeout``,
    ``headers``, ``auth_token``, ``max_response_bytes`` optionnels) vient de
    ``REMOTE_DATA["SERVICE_REGISTRY"][service]["http"]``.

    Fetches a remote resource via a conventional HTTP GET request.

    The source service must expose ``GET {base_url}/{resource}/{pk}/``
    returning a JSON object representing the resource. No particular REST
    framework is required on the source service side (a plain Django view
    is enough). Per-service config (``base_url``, optional ``timeout``,
    ``headers``, ``auth_token``, ``max_response_bytes``) comes from
    ``REMOTE_DATA["SERVICE_REGISTRY"][service]["http"]``.
    """

    def fetch(self, *, service: str, resource: str, pk: Any) -> dict[str, Any] | None:
        """Effectue le GET et renvoie le JSON décodé, ``None`` sur 404.

        Performs the GET and returns the decoded JSON, ``None`` on 404.
        """
        config = registry_entry(service, "http")
        base_url = str(config["base_url"]).rstrip("/")

        if remote_settings.REQUIRE_TLS and not base_url.startswith("https://"):
            raise RemoteServiceMisconfiguredError(
                f"REMOTE_DATA['REQUIRE_TLS'] est actif mais le service '{service}' "
                f"a un base_url non-https ({base_url}) / REMOTE_DATA['REQUIRE_TLS'] "
                f"is on but service '{service}' has a non-https base_url ({base_url})."
            )

        url = f"{base_url}/{resource}/{pk}/"

        headers = dict(config.get("headers") or {})
        auth_token = config.get("auth_token")
        if auth_token:
            # Symétrique de REMOTE_DATA["AUTH_TOKEN"] côté serveur
            # (resource_detail): évite d'avoir à reconstruire soi-même
            # l'en-tête Authorization via `headers`.
            #
            # Symmetric with the server-side REMOTE_DATA["AUTH_TOKEN"]
            # (resource_detail): avoids having to rebuild the Authorization
            # header by hand via `headers`.
            headers.setdefault("Authorization", f"Bearer {auth_token}")

        try:
            response = requests.get(
                url,
                timeout=config.get("timeout", 3),
                headers=headers or None,
                stream=True,
            )
        except requests.RequestException as exc:
            raise RemoteServiceUnavailableError(
                f"Requête HTTP vers '{service}' ({url}) impossible / failed: {exc}"
            ) from exc

        try:
            if response.status_code == 404:
                return None
            if not response.ok:
                raise RemoteServiceUnavailableError(
                    f"'{service}' a répondu {response.status_code} pour {url} / "
                    f"responded {response.status_code} for {url}"
                )

            max_bytes = config.get(
                "max_response_bytes", remote_settings.MAX_RESPONSE_BYTES
            )
            body = self._read_bounded(response, max_bytes, service=service, url=url)
        finally:
            response.close()

        try:
            return json.loads(body)
        except ValueError as exc:
            raise RemoteServiceUnavailableError(
                f"'{service}' a répondu un JSON invalide pour {url} / "
                f"responded invalid JSON for {url}: {exc}"
            ) from exc

    def _read_bounded(
        self, response: requests.Response, max_bytes: int, *, service: str, url: str
    ) -> bytes:
        """Lit le corps de ``response`` jusqu'à ``max_bytes``, sinon abandonne.

        Un pair "de confiance" compromis ou mal configuré pourrait
        renvoyer un corps de réponse démesuré; le lire en entier avant de
        vérifier sa taille exposerait le consommateur à une consommation
        mémoire non bornée — d'où une lecture par blocs, interrompue dès
        que la limite est dépassée.

        Reads ``response``'s body up to ``max_bytes``, aborting otherwise.

        A compromised or misconfigured "trusted" peer could return an
        oversized response body; reading it in full before checking its
        size would expose the consumer to unbounded memory use — hence a
        chunked read, aborted as soon as the limit is exceeded.
        """
        body = bytearray()
        for chunk in response.iter_content(chunk_size=_CHUNK_SIZE):
            body.extend(chunk)
            if len(body) > max_bytes:
                raise RemoteServiceUnavailableError(
                    f"'{service}' a dépassé la taille de réponse maximale "
                    f"({max_bytes} octets) pour {url} / exceeded the maximum "
                    f"response size ({max_bytes} bytes) for {url}"
                )
        return bytes(body)

    def close(self) -> None:
        """Rien à libérer: ``requests`` gère son propre pool de connexions.

        Nothing to release: ``requests`` manages its own connection pool.
        """
