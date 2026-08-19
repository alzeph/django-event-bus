from __future__ import annotations

from django_event_bus.remote.ratelimit import (
    RateLimitConfig,
    is_allowed,
    resolve_rate_limit_config,
)


class TestResolveRateLimitConfig:
    def test_none_when_raw_is_none(self):
        assert resolve_rate_limit_config(None) is None

    def test_none_when_raw_is_empty(self):
        assert resolve_rate_limit_config({}) is None

    def test_builds_config_from_raw_dict(self):
        config = resolve_rate_limit_config({"LIMIT": 5, "WINDOW_SECONDS": 30})

        assert config == RateLimitConfig(limit=5, window_seconds=30)

    def test_window_seconds_defaults_to_60(self):
        config = resolve_rate_limit_config({"LIMIT": 5})

        assert config is not None
        assert config.window_seconds == 60


class TestIsAllowed:
    def test_allows_calls_within_limit(self):
        config = RateLimitConfig(limit=3, window_seconds=60)

        results = [is_allowed(config, "caller-a") for _ in range(3)]

        assert results == [True, True, True]

    def test_denies_calls_past_limit(self):
        config = RateLimitConfig(limit=2, window_seconds=60)

        results = [is_allowed(config, "caller-b") for _ in range(3)]

        assert results == [True, True, False]

    def test_keys_are_isolated_per_caller(self):
        config = RateLimitConfig(limit=1, window_seconds=60)

        assert is_allowed(config, "caller-c") is True
        assert is_allowed(config, "caller-d") is True
        # Le premier appelant a déjà consommé son unique crédit.
        assert is_allowed(config, "caller-c") is False
