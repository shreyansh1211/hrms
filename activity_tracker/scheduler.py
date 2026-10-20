import logging

from horilla.scheduling import register_job

logger = logging.getLogger(__name__)


def sync_active_time():
    """Pull today's and yesterday's totals from the tracker (skipped if not configured)."""
    from activity_tracker import client, sync

    if not client.configured():
        return
    try:
        saved, unmatched = sync.sync_recent(2)
        if unmatched:
            logger.warning(
                "Active time: %d tracker employee(s) match no HRMS employee: %s",
                len(unmatched),
                ", ".join(unmatched[:5]),
            )
    except client.TrackerError as exc:
        logger.warning("Active time sync skipped: %s", exc)


def purge_old_active_time():
    """Keep one year of daily totals."""
    import datetime

    from activity_tracker.models import ActiveTimeDay

    ActiveTimeDay.objects.filter(
        date__lt=datetime.date.today() - datetime.timedelta(days=366)
    ).delete()


register_job(sync_active_time, "interval", job_id="active_time_sync", minutes=15, misfire_grace_time=600)
register_job(purge_old_active_time, "cron", job_id="active_time_purge", hour=3, minute=15, misfire_grace_time=3600)
