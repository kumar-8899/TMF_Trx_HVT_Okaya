"""Authenticators — the one pluggable seam (credential check)."""

from modules.auth.authenticators.no_auth import NoAuthAuthenticator
from modules.auth.authenticators.password import PasswordAuthenticator

BUILTIN = {
    PasswordAuthenticator.method_id: PasswordAuthenticator,
    NoAuthAuthenticator.method_id: NoAuthAuthenticator,
}


def make_authenticator(method_id: str):
    cls = BUILTIN.get(method_id)
    if cls is None:
        raise KeyError(f"unknown authenticator '{method_id}'")
    return cls()
