from django import template

register = template.Library()


@register.filter
def fmt_seconds(value):
    """
    Convert a seconds integer to a human-readable duration string.

    < 60 s   → "45s"
    < 3600 s → "5m 30s"  (omits seconds if exactly on the minute)
    ≥ 3600 s → "1h 30m"
    """
    try:
        s = int(value or 0)
    except (TypeError, ValueError):
        return "0s"

    if s < 60:
        return f"{s}s"

    if s < 3600:
        m = s // 60
        remaining = s % 60
        if remaining:
            return f"{m}m {remaining:02d}s"
        return f"{m}m"

    h = s // 3600
    m = (s % 3600) // 60
    return f"{h}h {m:02d}m"
