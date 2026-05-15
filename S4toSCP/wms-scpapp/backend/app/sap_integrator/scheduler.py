"""
scheduler.py — APScheduler integration manager

Manages one BackgroundScheduler job per integration.
Jobs can be added/removed at runtime when toggles change.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Dict

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .config import Settings, get_settings
from .integrations.items import ItemsIntegration
from .integrations.partners import PartnersIntegration
from .integrations.transfers import TransfersIntegration
from .integrations.stock_movements import StockMovementsIntegration
from .wms.sql_server import WMSDatabase

logger = logging.getLogger("scheduler")


class IntegrationScheduler:
    def __init__(self):
        self._scheduler = BackgroundScheduler(timezone="UTC")
        self._wms: WMSDatabase | None = None
        self._jobs: Dict[str, str] = {}  # name → job_id

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        settings = get_settings()
        self._wms = WMSDatabase(settings)

        # Attempt connection but do NOT crash if SQL Server is unreachable.
        # The integrations will retry on each job execution.
        try:
            self._wms.connect()
            logger.info("WMS SQL Server connected.")
        except Exception as e:
            logger.warning(
                f"Could not connect to WMS SQL Server on startup: {e}\n"
                "The integrator will start anyway. "
                "Fix the connection settings and restart, or the jobs will "
                "retry automatically on each run."
            )

        self._scheduler.start()
        self._apply_settings(settings)
        logger.info("Scheduler started.")

    def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
        if self._wms:
            self._wms.disconnect()
        logger.info("Scheduler stopped.")

    # ── Settings application ──────────────────────────────────────────────────

    def _apply_settings(self, settings: Settings) -> None:
        """Add/remove jobs based on current settings."""
        self._configure_job(
            name="items",
            enabled=settings.sync_items_enabled,
            interval=settings.interval_items,
            factory=lambda s, w: ItemsIntegration(s, w),
        )
        self._configure_job(
            name="partners",
            enabled=settings.sync_partners_enabled,
            interval=settings.interval_partners,
            factory=lambda s, w: PartnersIntegration(s, w),
        )
        self._configure_job(
            name="transfers",
            enabled=settings.sync_transfers_enabled,
            interval=settings.interval_transfers,
            factory=lambda s, w: TransfersIntegration(s, w),
        )
        self._configure_job(
            name="stock_movements",
            enabled=settings.sync_stock_movements_enabled,
            interval=settings.interval_stock_movements,
            factory=lambda s, w: StockMovementsIntegration(s, w),
        )

    def reload(self) -> None:
        """Called after config changes — re-apply all jobs."""
        settings = get_settings()
        self._apply_settings(settings)
        logger.info("Scheduler reloaded with new settings.")

    # ── Job management ────────────────────────────────────────────────────────

    def _configure_job(
        self,
        name: str,
        enabled: bool,
        interval: int,
        factory: Callable,
    ) -> None:
        existing_job_id = self._jobs.get(name)

        if not enabled:
            if existing_job_id:
                try:
                    self._scheduler.remove_job(existing_job_id)
                except Exception:
                    pass
                del self._jobs[name]
                logger.info(f"Job '{name}' disabled and removed.")
            return

        settings = get_settings()
        wms = self._wms

        def job_fn():
            integration = factory(settings, wms)
            asyncio.run(integration.execute())

        if existing_job_id:
            # Update interval if changed
            try:
                self._scheduler.reschedule_job(
                    existing_job_id,
                    trigger=IntervalTrigger(seconds=interval),
                )
                logger.info(f"Job '{name}' rescheduled to every {interval}s.")
            except Exception as e:
                logger.warning(f"Could not reschedule '{name}': {e}")
        else:
            job = self._scheduler.add_job(
                job_fn,
                trigger=IntervalTrigger(seconds=interval),
                id=name,
                name=name,
                replace_existing=True,
                max_instances=1,
                misfire_grace_time=30,
            )
            self._jobs[name] = job.id
            logger.info(f"Job '{name}' scheduled every {interval}s.")

    def toggle(self, name: str, enabled: bool) -> None:
        """Enable or disable a single integration without reloading all."""
        settings = get_settings()
        interval_map = {
            "items": settings.interval_items,
            "partners": settings.interval_partners,
            "transfers": settings.interval_transfers,
            "stock_movements": settings.interval_stock_movements,
        }
        factory_map = {
            "items": lambda s, w: ItemsIntegration(s, w),
            "partners": lambda s, w: PartnersIntegration(s, w),
            "transfers": lambda s, w: TransfersIntegration(s, w),
            "stock_movements": lambda s, w: StockMovementsIntegration(s, w),
        }
        self._configure_job(
            name=name,
            enabled=enabled,
            interval=interval_map[name],
            factory=factory_map[name],
        )

    def run_now(self, name: str) -> None:
        """Trigger an immediate run of a specific integration."""
        settings = get_settings()
        wms = self._wms
        factory_map = {
            "items": lambda: ItemsIntegration(settings, wms),
            "partners": lambda: PartnersIntegration(settings, wms),
            "transfers": lambda: TransfersIntegration(settings, wms),
            "stock_movements": lambda: StockMovementsIntegration(settings, wms),
        }
        if name not in factory_map:
            raise ValueError(f"Unknown integration: {name}")

        def job_fn():
            integration = factory_map[name]()
            asyncio.run(integration.execute())

        self._scheduler.add_job(
            job_fn,
            id=f"{name}_manual",
            replace_existing=True,
            max_instances=1,
        )
        logger.info(f"Manual run triggered for '{name}'.")

    def get_job_status(self) -> Dict[str, dict]:
        result = {}
        for name, job_id in self._jobs.items():
            job = self._scheduler.get_job(job_id)
            result[name] = {
                "scheduled": job is not None,
                "next_run": job.next_run_time.isoformat() if job and job.next_run_time else None,
            }
        return result


# Singleton
_scheduler: IntegrationScheduler | None = None


def get_scheduler() -> IntegrationScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = IntegrationScheduler()
    return _scheduler
