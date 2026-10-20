"""
Write the Infisetu-branded e-mail templates to Settings -> Email -> Templates.

    python manage.py seed_email_templates            # create missing, keep edits
    python manage.py seed_email_templates --reset    # overwrite with the originals
"""

from django.core.management.base import BaseCommand

from base.branded_email import TEMPLATES
from base.models import Company, HorillaMailTemplate


class Command(BaseCommand):
    help = "Create the branded e-mail templates"

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true")

    def handle(self, *args, **options):
        company = Company.objects.first()
        created = updated = 0
        for title, data in TEMPLATES.items():
            obj = HorillaMailTemplate.objects.filter(title=title).first()
            if obj is None:
                HorillaMailTemplate.objects.create(
                    title=title, body=data["body"], company_id=company
                )
                created += 1
            elif options["reset"]:
                obj.body = data["body"]
                obj.save()
                updated += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"E-mail templates: {created} created, {updated} reset, "
                f"{len(TEMPLATES)} in total."
            )
        )
