"""The production settings' throwaway environment: strong values no deployment ever holds."""

from __future__ import annotations

import base64
import os
import secrets


def production_env() -> dict[str, str]:
    """`config.settings.production`'s refusal set, each value generated for this one run."""
    return {
        "DJANGO_SETTINGS_MODULE": "config.settings.production",
        "DEBUG": "0",
        "ALLOWED_HOSTS": "example.invalid",
        "SECRET_KEY": "gate-only-" + secrets.token_hex(32),  # pragma: allowlist secret
        "CONNECTIONS_ENCRYPTION_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),
        "DATABASE_PASSWORD": "gate-only-" + secrets.token_urlsafe(24),  # pragma: allowlist secret
    }
