from django.core.management.base import BaseCommand

from base.models import Company
from horilla_theme.models import CompanyTheme, HorillaColorTheme

# Brand palette: logo 017391 / 0A17D3, website 2A7994 132238 38BDF8 64748B 33809A
INFISETU_THEME = {
    "name": "Infisetu Theme",
    "description": "Infisetu brand colours (teal 017391, navy 132238, sky 38BDF8)",
    "is_default": True,
    "primary_50": "#F4FAFC",
    "primary_100": "#E6F4F8",
    "primary_200": "#CFE9F1",
    "primary_300": "#A5D5E3",
    "primary_400": "#6DB9D0",
    "primary_500": "#33809A",
    "primary_600": "#017391",
    "primary_700": "#015F77",
    "primary_800": "#014A5E",
    "primary_900": "#132238",
    "dark_50": "#E6E6E6",
    "dark_100": "#A8A8A8",
    "dark_200": "#515151",
    "dark_300": "#132238",
    "dark_400": "#64748B",
    "dark_500": "#0B1424",
    "dark_600": "#000000",
    "secondary_50": "#f8fafc",
    "secondary_100": "#f1f5f9",
    "secondary_200": "#e2e8f0",
    "secondary_300": "#cbd5e1",
    "secondary_400": "#7DD3FC",
    "secondary_500": "#38BDF8",
    "secondary_600": "#2A7994",
    "secondary_700": "#334155",
    "secondary_800": "#1e293b",
    "secondary_900": "#132238",
}


class Command(BaseCommand):
    help = "Create the Infisetu colour theme, make it the default and apply it to every company"

    def handle(self, *args, **options):
        defaults = {k: v for k, v in INFISETU_THEME.items() if k != "name"}
        theme, _ = HorillaColorTheme.objects.update_or_create(
            name=INFISETU_THEME["name"], defaults=defaults
        )
        for company in Company.objects.all():
            CompanyTheme.objects.update_or_create(
                company=company, defaults={"theme": theme}
            )
        self.stdout.write(self.style.SUCCESS(f"Applied '{theme.name}'"))
