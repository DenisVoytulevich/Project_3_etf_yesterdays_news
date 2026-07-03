import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import Settings

logger = logging.getLogger(__name__)


def setup_scheduler(
    settings: Settings,
    on_daily_briefing,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.timezone)

    scheduler.add_job(
        on_daily_briefing,
        CronTrigger(
            hour=settings.daily_briefing_hour,
            minute=settings.daily_briefing_minute,
        ),
        id="daily_briefing",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    logger.info(
        "Планировщик: ежедневный брифинг в %02d:%02d (%s)",
        settings.daily_briefing_hour,
        settings.daily_briefing_minute,
        settings.timezone,
    )
    return scheduler
