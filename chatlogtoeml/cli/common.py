"""Shared helpers for CLI entrypoints."""


def sanitize_chat_id(chat_id: str, maxlen: int = 64) -> str:
    # Replace non-alnum with underscores, trim to maxlen, and strip leading underscores.
    safe = ''.join([c if c.isalnum() else '_' for c in (chat_id or '')])
    safe = safe[:maxlen]
    return safe.lstrip('_')


def make_out_filename(chat_id: str, startdate, idx: int) -> str:
    # Prefer full timestamp first for sortable filenames: YYYY-MM-DDTHHMMSS.
    if hasattr(startdate, 'strftime'):
        datepart = startdate.strftime('%Y-%m-%dT%H%M%S')
    elif hasattr(startdate, 'date'):
        datepart = startdate.date().isoformat()
    else:
        datepart = 'nodate'
    sanitized = sanitize_chat_id(chat_id) or 'chat'
    return f"{datepart}_{sanitized}_{idx:04d}.eml"


__all__ = ['sanitize_chat_id', 'make_out_filename']
