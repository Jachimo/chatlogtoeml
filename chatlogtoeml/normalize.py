"""Shared normalization helpers for user/account identifiers."""

from typing import Any, Iterable, Optional


USER_IDENTIFIER_KEYS = (
    'id',
    'identifier',
    'handle',
    'address',
    'username',
    'phone',
    'value',
)


def normalize_user(value: Any, lowercase: bool = False, dict_keys: Iterable[str] = USER_IDENTIFIER_KEYS) -> Optional[str]:
    """Normalize a user-like value to a string.

    Behavior intentionally mirrors existing parser logic:
    - None/falsey input -> None
    - dict input -> first non-empty common key, then first non-empty value
    - otherwise -> str(value)
    """
    if not value:
        return None

    resolved = value
    if isinstance(value, dict):
        resolved = None
        for key in dict_keys:
            candidate = value.get(key)
            if candidate:
                resolved = candidate
                break
        if resolved is None:
            for candidate in value.values():
                if candidate:
                    resolved = candidate
                    break
        if resolved is None:
            return None

    try:
        text = str(resolved)
    except Exception:
        return None

    if lowercase:
        text = text.lower()
    return text


def normalize_user_lowercase(value: Any) -> str:
    """Normalize values for case-insensitive userid comparisons."""
    return normalize_user(value, lowercase=True) or ''


__all__ = ['normalize_user', 'normalize_user_lowercase']
