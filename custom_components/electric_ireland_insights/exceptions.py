"""Custom exceptions for Electric Ireland integration."""

from __future__ import annotations


class InvalidAuth(Exception):
    """Raised when authentication fails."""


class CannotConnect(Exception):
    """Raised when connection to Electric Ireland fails."""


class AccountNotFound(Exception):
    """Raised when the specified account number is not found."""


class CachedIdsInvalid(Exception):
    """Raised when cached meter IDs are no longer valid."""
