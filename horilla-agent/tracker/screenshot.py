"""
Captures a JPEG screenshot of the primary monitor and returns it as base64.

Uses mss (fast, cross-platform, no display server required on Windows).
"""
import base64
import io
import time


def capture_jpeg(quality: int = 60) -> str | None:
    """
    Capture a screenshot and return it as a base64-encoded JPEG string.
    Returns None on failure.
    """
    try:
        import mss
        import mss.tools
        from PIL import Image

        with mss.mss() as sct:
            monitor = sct.monitors[1]  # primary monitor
            raw = sct.grab(monitor)
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
            # Scale down to max 1280px wide to keep size small
            if img.width > 1280:
                scale = 1280 / img.width
                img = img.resize(
                    (1280, int(img.height * scale)), Image.LANCZOS
                )
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None
