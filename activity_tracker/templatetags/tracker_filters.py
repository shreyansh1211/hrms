from django import template

register = template.Library()


@register.filter
def fmt_seconds(value):
    """Convert seconds integer to '2h 14m' string."""
    try:
        s = int(value or 0)
    except (TypeError, ValueError):
        return "0h 00m"
    h, rem = divmod(s, 3600)
    return f"{h}h {rem // 60:02d}m"
