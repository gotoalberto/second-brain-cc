"""Tokens for unattended callers (the guardian's mailer, routines): never a prompt, always bounded."""

from __future__ import annotations

from . import adapters, application


def access_token(account, required_scope=None, timeout=20, environ=None):
    """A fresh access token for the google.py account `account`. Raises domain.GoogleError subclasses."""
    ports = adapters.build_ports(environ, headless=True, open_browser=False)
    return application.access_token(ports, account, required_scope, timeout)
