"""Doublures de test pour le volet « récupération de données inter-services »."""

from __future__ import annotations

from typing import Any, ClassVar

from django_event_bus.exceptions import RemoteServiceUnavailableError
from django_event_bus.remote.transports.base import BaseTransport


class FakeTransport(BaseTransport):
    """Transport de test, en mémoire, sans réseau ni gRPC réel."""

    calls: ClassVar[list[tuple[str, str, Any]]] = []
    data: ClassVar[dict[tuple[str, str, Any], dict[str, Any]]] = {}
    fail_on: ClassVar[set[tuple[str, str, Any]]] = set()

    def fetch(self, *, service: str, resource: str, pk: Any) -> dict[str, Any] | None:
        key = (service, resource, pk)
        FakeTransport.calls.append(key)
        if key in FakeTransport.fail_on:
            raise RemoteServiceUnavailableError("panne simulée pour les tests")
        return FakeTransport.data.get(key)

    @classmethod
    def reset(cls) -> None:
        cls.calls.clear()
        cls.data.clear()
        cls.fail_on.clear()
