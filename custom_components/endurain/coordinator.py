"""Coordinator for Endurain."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import EndurainApiClient
from .const import (
    CONF_ENABLE_GEARS,
    CONF_ENABLE_GOALS,
    CONF_ENABLE_HEALTH,
    CONF_ENABLE_LIFETIME,
    DEFAULT_ENABLE_GEARS,
    DEFAULT_ENABLE_GOALS,
    DEFAULT_ENABLE_HEALTH,
    DEFAULT_ENABLE_LIFETIME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .exceptions import EndurainApiError, EndurainAuthError, EndurainMfaRequiredError, EndurainRateLimitError
from .repairs import async_create_auth_issue, async_delete_auth_issue

_LOGGER = logging.getLogger(__name__)


class EndurainCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinate Endurain API polling."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: EndurainApiClient,
    ) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        self.client = client
        scan_interval = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch the latest data from Endurain."""
        include_goals = self.entry.options.get(CONF_ENABLE_GOALS, DEFAULT_ENABLE_GOALS)
        include_health = self.entry.options.get(CONF_ENABLE_HEALTH, DEFAULT_ENABLE_HEALTH)
        include_gears = self.entry.options.get(CONF_ENABLE_GEARS, DEFAULT_ENABLE_GEARS)
        include_lifetime = self.entry.options.get(CONF_ENABLE_LIFETIME, DEFAULT_ENABLE_LIFETIME)

        try:
            summary_coros = {
                "weekly": self.client.async_fetch_summary("week"),
                "monthly": self.client.async_fetch_summary("month"),
                "yearly": self.client.async_fetch_summary("year"),
            }
            if include_lifetime:
                summary_coros["lifetime"] = self.client.async_fetch_summary("lifetime")

            about_task = self.client.async_fetch_about()
            profile_task = self.client.async_fetch_profile()
            notifications_task = self.client.async_fetch_notifications_number()

            results = await asyncio.gather(
                about_task,
                profile_task,
                notifications_task,
                *summary_coros.values(),
                return_exceptions=False,
            )
            about = results[0]
            profile = results[1]
            notifications = results[2]
            summaries = {
                key: results[index]
                for index, key in enumerate(summary_coros.keys(), start=3)
            }
            latest_activity = None
            latest_activity_streams: list[dict[str, Any]] = []
            latest_activity_laps: list[dict[str, Any]] = []
            user_id = profile.get("id")
            if isinstance(user_id, int):
                latest_activity = await self.client.async_fetch_latest_activity(user_id)
                activity_id = latest_activity.get("id") if isinstance(latest_activity, dict) else None
                if isinstance(activity_id, int):
                    try:
                        latest_activity_streams = await self.client.async_fetch_activity_streams(
                            activity_id
                        )
                    except EndurainApiError:
                        _LOGGER.warning(
                            "Failed to fetch streams for latest Endurain activity %s",
                            activity_id,
                        )
                    try:
                        latest_activity_laps = await self.client.async_fetch_activity_laps(
                            activity_id
                        )
                    except EndurainApiError:
                        _LOGGER.warning(
                            "Failed to fetch laps for latest Endurain activity %s",
                            activity_id,
                        )

            goals: list[dict[str, Any]] = []
            latest_steps: dict[str, Any] | None = None
            latest_sleep: dict[str, Any] | None = None
            latest_weight: dict[str, Any] | None = None
            gear_stats: list[dict[str, Any]] = []

            optional_tasks: list[asyncio.Future[Any] | asyncio.Task[Any] | Any] = []
            task_names: list[str] = []

            if include_goals:
                optional_tasks.append(self.client.async_fetch_goals_progress())
                task_names.append("goals")
            if include_health:
                optional_tasks.extend(
                    [
                        self.client.async_fetch_health_steps(),
                        self.client.async_fetch_health_sleep(),
                        self.client.async_fetch_health_weight(),
                    ]
                )
                task_names.extend(["steps", "sleep", "weight"])
            if include_gears:
                optional_tasks.append(self.client.async_fetch_gear_stats())
                task_names.append("gears")

            if optional_tasks:
                optional_results = await asyncio.gather(*optional_tasks, return_exceptions=False)
                for name, result in zip(task_names, optional_results, strict=False):
                    if name == "goals":
                        goals = result
                    elif name == "steps":
                        latest_steps = result
                    elif name == "sleep":
                        latest_sleep = result
                    elif name == "weight":
                        latest_weight = result
                    elif name == "gears":
                        gear_stats = result

            async_delete_auth_issue(self.hass, self.entry)
            return {
                "about": about,
                "profile": profile,
                "notifications": notifications,
                "summaries": summaries,
                "latest_activity": latest_activity,
                "latest_activity_streams": latest_activity_streams,
                "latest_activity_laps": latest_activity_laps,
                "goals": goals,
                "latest_steps": latest_steps,
                "latest_sleep": latest_sleep,
                "latest_weight": latest_weight,
                "gear_stats": gear_stats,
            }
        except (EndurainAuthError, EndurainMfaRequiredError) as err:
            async_create_auth_issue(self.hass, self.entry, str(err))
            raise ConfigEntryAuthFailed(str(err)) from err
        except EndurainRateLimitError as err:
            retry_hint = f" Retry after {err.retry_after}s." if err.retry_after is not None else ""
            raise UpdateFailed(f"Endurain rate limit exceeded.{retry_hint}") from err
        except EndurainApiError as err:
            raise UpdateFailed(str(err)) from err
