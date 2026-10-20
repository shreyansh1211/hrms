from datetime import date

from django.core.management.base import BaseCommand

from asset.models import Asset, AssetCategory
from base.models import Company

# (category name, tracking-id prefix, default count)
ITEM_TYPES = [
    ("Laptop", "INF-LAP", 10),
    ("Mouse", "INF-MOU", 10),
    ("Keyboard", "INF-KEY", 10),
    ("Headphone", "INF-HDP", 5),
    ("Laptop Stand", "INF-STD", 5),
    ("Laptop Cooling Fan", "INF-FAN", 5),
]


class Command(BaseCommand):
    help = (
        "Create IT asset categories and individually trackable assets "
        "(INF-LAP-001, INF-MOU-001, ...). Safe to re-run: existing IDs are skipped."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            help="Create this many of every type instead of the per-type defaults",
        )

    def handle(self, *args, **options):
        companies = list(Company.objects.all())
        for name, prefix, default_count in ITEM_TYPES:
            count = options["count"] or default_count
            category, _ = AssetCategory.objects.get_or_create(
                asset_category_name=name,
                defaults={"asset_category_description": f"{name} (IT equipment)"},
            )
            category.company_id.add(*companies)
            created = 0
            for number in range(1, count + 1):
                tracking_id = f"{prefix}-{number:03d}"
                _, was_created = Asset.objects.get_or_create(
                    asset_tracking_id=tracking_id,
                    defaults={
                        "asset_name": name,
                        "asset_category_id": category,
                        "asset_purchase_date": date.today(),
                        "asset_purchase_cost": 0,
                        "quantity": 1,
                    },
                )
                created += was_created
            self.stdout.write(f"{name}: {created} created ({prefix}-001 ...)")
