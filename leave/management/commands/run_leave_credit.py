"""
python manage.py run_leave_credit --date 2026-12-01
python manage.py run_leave_credit --date 2026-12-01 --dry-run
python manage.py run_leave_credit --year-end --date 2026-03-31
python manage.py run_leave_credit --year-end --date 2026-03-31 --dry-run
"""

from datetime import date

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Manually run a leave cycle credit or year-end carry-forward."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            required=True,
            help="Credit date in YYYY-MM-DD format (e.g. 2026-12-01).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Print what would happen without writing anything.",
        )
        parser.add_argument(
            "--year-end",
            action="store_true",
            default=False,
            help="Run the year-end carry-forward instead of a cycle credit.",
        )

    def handle(self, *args, **options):
        try:
            credit_date = date.fromisoformat(options["date"])
        except ValueError as exc:
            raise CommandError(f"Invalid date: {options['date']}. Use YYYY-MM-DD.") from exc

        dry_run = options["dry_run"]
        mode = "year-end carry-forward" if options["year_end"] else "cycle credit"
        prefix = "[DRY RUN] " if dry_run else ""

        self.stdout.write(
            self.style.WARNING(
                f"{prefix}Running {mode} for {credit_date}"
                + (" (dry-run — no DB writes)" if dry_run else "")
            )
        )

        if options["year_end"]:
            from leave.credit_service import apply_year_end_carryforward

            result = apply_year_end_carryforward(as_of_date=credit_date, dry_run=dry_run)
            for line in result.get("carried", []):
                self.stdout.write(f"  CARRY  {line}")
            for line in result.get("zeroed", []):
                self.stdout.write(f"  ZERO   {line}")
        else:
            from leave.credit_service import apply_cycle_credits, get_cycle_for_date

            cycle = get_cycle_for_date(credit_date)
            if cycle is None:
                raise CommandError(
                    f"{credit_date} is not a cycle credit date "
                    "(expected Apr 1, Aug 1, or Dec 1)."
                )
            result = apply_cycle_credits(credit_date=credit_date, dry_run=dry_run)
            for line in result.get("credited", []):
                self.stdout.write(f"  CREDIT  {line}")
            for line in result.get("skipped", []):
                self.stdout.write(self.style.WARNING(f"  SKIP    {line}"))

        errors = result.get("errors", [])
        for line in errors:
            self.stdout.write(self.style.ERROR(f"  ERROR   {line}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. credited/carried={len(result.get('credited') or result.get('carried',[]))}, "
                f"skipped/zeroed={len(result.get('skipped') or result.get('zeroed',[]))}, "
                f"errors={len(errors)}"
            )
        )
