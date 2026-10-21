# Migration: replace the default "Coral Red" palette with the Horilla Teal palette.
# All primary_* / secondary_* / dark_* fields for the is_default=True theme are
# updated in a single RunPython step so the DB stays in sync with THEMES_DATA.

from django.db import migrations

TEAL_THEME = {
    "name":          "Horilla Teal Theme (Default)",
    "description":   "Professional teal-based theme",
    "primary_50":    "#f0fafb",
    "primary_100":   "#e0f4f7",
    "primary_200":   "#c1e9f0",
    "primary_300":   "#89d1e3",
    "primary_400":   "#4db8d4",
    "primary_500":   "#26a0be",
    "primary_600":   "#017391",
    "primary_700":   "#015f78",
    "primary_800":   "#014d61",
    "primary_900":   "#013847",
    "dark_50":       "#E6E6E6",
    "dark_100":      "#A8A8A8",
    "dark_200":      "#515151",
    "dark_300":      "#015f78",
    "dark_400":      "#64748B",
    "dark_500":      "#013847",
    "dark_600":      "#000000",
    "secondary_50":  "#f8fafc",
    "secondary_100": "#f1f5f9",
    "secondary_200": "#e2e8f0",
    "secondary_300": "#cbd5e1",
    "secondary_400": "#c1e9f0",
    "secondary_500": "#89d1e3",
    "secondary_600": "#017391",
    "secondary_700": "#334155",
    "secondary_800": "#1e293b",
    "secondary_900": "#0f172a",
}


def update_default_theme(apps, schema_editor):
    HorillaColorTheme = apps.get_model("horilla_theme", "HorillaColorTheme")
    theme = HorillaColorTheme.objects.filter(is_default=True).first()
    if theme:
        for field, value in TEAL_THEME.items():
            setattr(theme, field, value)
        theme.save()
    else:
        # No default theme in DB yet — create it so it matches THEMES_DATA
        HorillaColorTheme.objects.create(is_default=True, **TEAL_THEME)


def revert_default_theme(apps, schema_editor):
    """Reverse: restore the original Coral Red palette."""
    CORAL_RED = {
        "name":          "Coral Red Theme (Default)",
        "description":   "Warm coral-red based theme",
        "primary_50":    "#f6f6f6",
        "primary_100":   "#FFF5F1",
        "primary_200":   "#FEF6F5",
        "primary_300":   "#FCEDEB",
        "primary_400":   "#FBE5E1",
        "primary_500":   "#F7C8C1",
        "primary_600":   "#E54F38",
        "primary_700":   "#ce4732",
        "primary_800":   "#AC3B2A",
        "primary_900":   "#672419",
        "dark_50":       "#E6E6E6",
        "dark_100":      "#A8A8A8",
        "dark_200":      "#515151",
        "dark_300":      "#501C14",
        "dark_400":      "#64748B",
        "dark_500":      "#190906",
        "dark_600":      "#000000",
        "secondary_50":  "#f8fafc",
        "secondary_100": "#f1f5f9",
        "secondary_200": "#e2e8f0",
        "secondary_300": "#cbd5e1",
        "secondary_400": "#FBE5E1",
        "secondary_500": "#F7C8C1",
        "secondary_600": "#E54F38",
        "secondary_700": "#334155",
        "secondary_800": "#1e293b",
        "secondary_900": "#0f172a",
    }
    HorillaColorTheme = apps.get_model("horilla_theme", "HorillaColorTheme")
    theme = HorillaColorTheme.objects.filter(is_default=True).first()
    if theme:
        for field, value in CORAL_RED.items():
            setattr(theme, field, value)
        theme.save()


class Migration(migrations.Migration):

    dependencies = [
        ("horilla_theme", "0002_alter_companytheme_is_active_and_more"),
    ]

    operations = [
        migrations.RunPython(update_default_theme, revert_default_theme),
    ]
