"""Input sanitization utilities to prevent XSS and injection attacks."""

import html


def sanitize_string(value):
    """Escape HTML entities in a string.

    Converts < > & " ' to their HTML entity equivalents so that
    user-supplied strings cannot inject markup or script tags.
    """
    if not isinstance(value, str):
        return value
    return html.escape(value, quote=True)


def sanitize_dict(data):
    """Recursively walk a dict/list structure and sanitize all string values.

    Non-string leaves (int, float, bool, None) are returned unchanged.
    """
    if isinstance(data, dict):
        return {key: sanitize_dict(value) for key, value in data.items()}
    if isinstance(data, list):
        return [sanitize_dict(item) for item in data]
    if isinstance(data, str):
        return sanitize_string(data)
    # int, float, bool, None, etc. – pass through untouched
    return data
