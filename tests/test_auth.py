from __future__ import annotations

import time

import jwt
import pytest
from django.test import override_settings

from django_event_bus.exceptions import ImproperlyConfiguredError
from django_event_bus.remote.auth import (
    AllowAllAuthBackend,
    JWTAuthBackend,
    StaticTokenAuthBackend,
    resolve_auth_backend,
)


def test_allow_all_backend_always_grants():
    result = AllowAllAuthBackend().authenticate(None)

    assert result.granted is True
    assert result.caller is None


class TestStaticTokenAuthBackend:
    def test_grants_matching_bearer_token(self):
        backend = StaticTokenAuthBackend("s3cr3t")

        result = backend.authenticate("Bearer s3cr3t")

        assert result.granted is True
        assert result.caller == "shared-token"

    def test_denies_missing_header(self):
        backend = StaticTokenAuthBackend("s3cr3t")

        result = backend.authenticate(None)

        assert result.granted is False
        assert result.reason

    def test_denies_wrong_token(self):
        backend = StaticTokenAuthBackend("s3cr3t")

        result = backend.authenticate("Bearer nope")

        assert result.granted is False


class TestJWTAuthBackend:
    def _token(
        self,
        *,
        key="s3cr3t-test-signing-key-32-bytes-long",
        exp_delta=300,
        **extra_claims,
    ):
        claims = {"exp": int(time.time()) + exp_delta, **extra_claims}
        return jwt.encode(claims, key, algorithm="HS256")

    def test_grants_valid_token_and_exposes_subject_as_caller(self):
        backend = JWTAuthBackend("s3cr3t-test-signing-key-32-bytes-long")
        token = self._token(sub="service_order")

        result = backend.authenticate(f"Bearer {token}")

        assert result.granted is True
        assert result.caller == "service_order"

    def test_denies_missing_bearer_prefix(self):
        backend = JWTAuthBackend("s3cr3t-test-signing-key-32-bytes-long")

        result = backend.authenticate(self._token())

        assert result.granted is False

    def test_denies_missing_header(self):
        backend = JWTAuthBackend("s3cr3t-test-signing-key-32-bytes-long")

        result = backend.authenticate(None)

        assert result.granted is False

    def test_denies_expired_token(self):
        backend = JWTAuthBackend("s3cr3t-test-signing-key-32-bytes-long")
        token = self._token(exp_delta=-10)

        result = backend.authenticate(f"Bearer {token}")

        assert result.granted is False
        assert "invalid JWT" in (result.reason or "")

    def test_denies_wrong_signing_key(self):
        backend = JWTAuthBackend("s3cr3t-test-signing-key-32-bytes-long")
        token = self._token(key="wrong-key")

        result = backend.authenticate(f"Bearer {token}")

        assert result.granted is False

    def test_denies_token_missing_exp_claim(self):
        backend = JWTAuthBackend("s3cr3t-test-signing-key-32-bytes-long")
        token = jwt.encode(
            {"sub": "x"}, "s3cr3t-test-signing-key-32-bytes-long", algorithm="HS256"
        )

        result = backend.authenticate(f"Bearer {token}")

        assert result.granted is False

    def test_enforces_audience_when_configured(self):
        backend = JWTAuthBackend(
            "s3cr3t-test-signing-key-32-bytes-long", audience="service_auth"
        )
        token = self._token(aud="someone_else")

        result = backend.authenticate(f"Bearer {token}")

        assert result.granted is False

    def test_falls_back_to_issuer_when_no_subject(self):
        backend = JWTAuthBackend("s3cr3t-test-signing-key-32-bytes-long")
        token = self._token(iss="service_order")

        result = backend.authenticate(f"Bearer {token}")

        assert result.granted is True
        assert result.caller == "service_order"


def test_jwt_backend_requires_pyjwt(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "jwt":
            raise ImportError("no module named jwt")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(ImproperlyConfiguredError, match="PyJWT"):
        JWTAuthBackend("s3cr3t-test-signing-key-32-bytes-long")


class TestResolveAuthBackend:
    def test_defaults_to_allow_all(self):
        with override_settings(REMOTE_DATA={}):
            backend = resolve_auth_backend()

        assert isinstance(backend, AllowAllAuthBackend)

    def test_auth_token_shorthand_builds_static_backend(self):
        with override_settings(REMOTE_DATA={"AUTH_TOKEN": "s3cr3t"}):
            backend = resolve_auth_backend()

        assert isinstance(backend, StaticTokenAuthBackend)
        assert backend.authenticate("Bearer s3cr3t").granted is True

    def test_auth_backend_setting_takes_precedence_over_auth_token(self):
        with override_settings(
            REMOTE_DATA={
                "AUTH_TOKEN": "ignored",
                "AUTH_BACKEND": "django_event_bus.remote.auth.AllowAllAuthBackend",
            }
        ):
            backend = resolve_auth_backend()

        assert isinstance(backend, AllowAllAuthBackend)
