"""A production deploy must not start with placeholder secrets or open CORS."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tests import support  # noqa: F401  (pins the environment before src imports)

from src.settings import Settings


def _settings(**overrides):
    base = {
        "secret_key": "k" * 40,
        "service_prefix": "call",
        "application_state": "production",
        "origins": "https://admin.example.com",
        "db": {"host": "h", "port": 5432, "user": "u", "password": "p"},
        "redis": {"type": "standalone", "host": "h", "port": 6379, "password": "p"},
    }
    return Settings(**{**base, **overrides})


def test_a_proper_production_config_loads():
    assert _settings().application_state.is_production


@pytest.mark.parametrize("secret", ["change-me-to-a-random-secret", "short"])
def test_production_refuses_a_placeholder_or_short_secret(secret):
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        _settings(secret_key=secret)


def test_production_refuses_wildcard_origins():
    with pytest.raises(ValidationError, match="ORIGINS"):
        _settings(origins="*")


def test_development_keeps_working_with_the_example_values():
    _settings(
        application_state="development",
        secret_key="change-me-to-a-random-secret",
        origins="*",
    )
