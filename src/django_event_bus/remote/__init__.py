"""Récupération (``RemoteForeignKey``) et exposition (``expose_resource``) de données.

Retrieval (``RemoteForeignKey``) and exposure (``expose_resource``) of data.
"""

from ..exceptions import (
    ImproperlyConfiguredError,
    RemoteServiceMisconfiguredError,
    RemoteServiceUnavailableError,
)
from .fields import RemoteForeignKey
from .objects import RemoteObject
from .resources import ResourceSerializer, expose_resource

__all__ = [
    "ImproperlyConfiguredError",
    "RemoteForeignKey",
    "RemoteObject",
    "RemoteServiceMisconfiguredError",
    "RemoteServiceUnavailableError",
    "ResourceSerializer",
    "expose_resource",
]
