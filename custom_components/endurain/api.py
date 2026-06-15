"""API client for Endurain."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import date, timedelta
import json
from typing import Any

import aiohttp

from .exceptions import (
    EndurainApiError,
    EndurainAuthError,
    EndurainMfaRequiredError,
    EndurainRateLimitError,
)


class EndurainApiClient:
    """Async API client for Endurain."""

    def __init__(
        self,
        *,
        session: aiohttp.ClientSession,
        base_url: str,
        username: str,
        password: str,
        mfa_code: str | None = None,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._mfa_code = mfa_code
        self._access_token: str | None = None
        self._auth_lock = asyncio.Lock()
        self._login_retry_at: float = 0.0

    @property
    def base_url(self) -> str:
        """Return the normalized base URL."""
        return self._base_url

    @property
    def username(self) -> str:
        """Return the configured username."""
        return self._username

    def update_credentials(
        self,
        *,
        base_url: str,
        username: str,
        password: str,
        mfa_code: str | None,
    ) -> None:
        """Update runtime credentials."""
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._mfa_code = mfa_code
        self._access_token = None

    async def async_validate(self, mfa_code: str | None = None) -> dict[str, Any]:
        """Validate credentials and return basic profile metadata."""
        await self.async_login(mfa_code=mfa_code)
        about, profile = await self.async_fetch_about(), await self.async_fetch_profile()
        return {"about": about, "profile": profile}

    async def async_login(self, *, mfa_code: str | None = None) -> str:
        """Authenticate against Endurain."""
        async with self._auth_lock:
            if self._access_token is not None:
                return self._access_token

            loop = asyncio.get_running_loop()
            delay = self._login_retry_at - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)

            payload = {"username": self._username, "password": self._password}
            response = await self._raw_request(
                "post",
                "/api/v1/auth/login",
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-Client-Type": "mobile",
                },
                data=payload,
                auth=False,
                retry_on_auth=False,
            )
            body = await self._decode_response(response)

            if response.status == 429:
                retry_after = self._extract_retry_after(body) or 60
                self._login_retry_at = loop.time() + retry_after
                raise EndurainRateLimitError(
                    self._extract_error_message(body, "Rate limit exceeded"),
                    retry_after=retry_after,
                )

            if response.status < 200 or response.status >= 300:
                raise EndurainAuthError(self._extract_error_message(body, "Login failed"))

            if isinstance(body, Mapping) and body.get("mfa_required"):
                code = mfa_code or self._mfa_code
                if not code:
                    raise EndurainMfaRequiredError("MFA is required")
                body = await self.async_verify_mfa(code)

            if not isinstance(body, Mapping) or not body.get("access_token"):
                raise EndurainAuthError("Login response missing access token")

            self._login_retry_at = 0.0
            self._access_token = str(body["access_token"])
            return self._access_token

    async def async_verify_mfa(self, code: str) -> dict[str, Any]:
        """Complete MFA verification."""
        response = await self._raw_request(
            "post",
            "/api/v1/auth/mfa/verify",
            headers={
                "Content-Type": "application/json",
                "X-Client-Type": "mobile",
            },
            json_data={"username": self._username, "mfa_code": code},
            auth=False,
            retry_on_auth=False,
        )
        body = await self._decode_response(response)
        if response.status < 200 or response.status >= 300:
            raise EndurainAuthError(self._extract_error_message(body, "MFA verification failed"))
        if not isinstance(body, Mapping):
            raise EndurainAuthError("MFA verification response was not JSON")
        self._mfa_code = code
        return dict(body)

    async def async_fetch_about(self) -> dict[str, Any]:
        """Fetch API metadata."""
        data = await self._request_json("get", "/api/v1/about", auth=False)
        if not isinstance(data, Mapping):
            raise EndurainApiError("Unexpected about payload")
        return dict(data)

    async def async_fetch_profile(self) -> dict[str, Any]:
        """Fetch the current user profile."""
        data = await self._request_json("get", "/api/v1/profile")
        if not isinstance(data, Mapping):
            raise EndurainApiError("Unexpected profile payload")
        return dict(data)

    async def async_fetch_summary(self, view_type: str) -> dict[str, Any]:
        """Fetch a summary view."""
        data = await self._request_json("get", f"/api/v1/activities_summaries/{view_type}")
        if not isinstance(data, Mapping):
            raise EndurainApiError(f"Unexpected {view_type} summary payload")
        return dict(data)

    async def async_fetch_goals_progress(self) -> list[dict[str, Any]]:
        """Fetch goal progress."""
        data = await self._request_json("get", "/api/v1/profile/goals/results")
        if data is None:
            return []
        if not isinstance(data, list):
            raise EndurainApiError("Unexpected goals payload")
        return [dict(item) for item in data if isinstance(item, Mapping)]

    async def async_fetch_latest_activity(self, user_id: int) -> dict[str, Any] | None:
        """Fetch the most recent activity for the configured user."""
        data = await self._request_json(
            "get",
            f"/api/v1/activities/user/{user_id}/page_number/1/num_records/1",
        )
        if data is None:
            return None
        if not isinstance(data, list):
            raise EndurainApiError("Unexpected latest activity payload")
        for item in data:
            if isinstance(item, Mapping):
                return dict(item)
        return None

    async def async_fetch_activity_streams(self, activity_id: int) -> list[dict[str, Any]]:
        """Fetch all activity streams for the given activity."""
        data = await self._request_json(
            "get",
            f"/api/v1/activities_streams/activity_id/{activity_id}/all",
        )
        if data is None:
            return []
        if not isinstance(data, list):
            raise EndurainApiError("Unexpected activity streams payload")
        return [dict(item) for item in data if isinstance(item, Mapping)]

    async def async_fetch_notifications_number(self) -> int:
        """Fetch the unread notifications count."""
        data = await self._request_json("get", "/api/v1/notifications/number")
        if isinstance(data, int):
            return data
        raise EndurainApiError("Unexpected notifications payload")

    async def async_fetch_health_steps(self) -> dict[str, Any] | None:
        """Fetch the latest steps record."""
        data = await self._request_json("get", "/api/v1/health/steps")
        return self._latest_record(data, primary_key="date")

    async def async_fetch_health_sleep(self) -> dict[str, Any] | None:
        """Fetch the latest sleep record."""
        data = await self._request_json("get", "/api/v1/health/sleep")
        return self._latest_record(data, primary_key="sleep_end_time_local", secondary_key="date")

    async def async_fetch_health_weight(self) -> dict[str, Any] | None:
        """Fetch the latest weight record."""
        data = await self._request_json("get", "/api/v1/health/weight")
        return self._latest_record(data, primary_key="date")

    async def async_fetch_gear_stats(self) -> list[dict[str, Any]]:
        """Fetch gear metadata enriched with usage stats."""
        gears = await self._request_json("get", "/api/v1/gears")
        if gears is None:
            return []
        if not isinstance(gears, list):
            raise EndurainApiError("Unexpected gears payload")

        enriched: list[dict[str, Any]] = []
        for gear in gears:
            if not isinstance(gear, Mapping):
                continue
            gear_dict = dict(gear)
            gear_id = gear_dict.get("id")
            activities: list[dict[str, Any]] = []
            if gear_id is not None:
                payload = await self._request_json("get", f"/api/v1/activities/gear/{gear_id}")
                if isinstance(payload, list):
                    activities = [dict(item) for item in payload if isinstance(item, Mapping)]
            enriched.append(self._build_gear_stats(gear_dict, activities))
        return enriched

    async def async_sync_recent_strava(self, days: int) -> None:
        """Trigger a Strava activity sync for the last N days."""
        start_date = date.today() - timedelta(days=days)
        end_date = date.today()
        await self._request_json(
            "get",
            "/api/v1/strava/activities",
            params={
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
        )

    async def async_sync_strava_gear(self) -> None:
        """Trigger a Strava gear sync."""
        await self._request_json("get", "/api/v1/strava/gear")

    async def async_refresh_activities(self) -> None:
        """Trigger an activity refresh."""
        await self._request_json("get", "/api/v1/activities/refresh")

    async def async_bulk_import(self) -> None:
        """Trigger Endurain's bulk import pipeline."""
        await self._request_json("post", "/api/v1/activities/create/bulkimport")

    async def async_import_strava_shoes(self) -> None:
        """Import shoes from Strava export data."""
        await self._request_json("post", "/api/v1/strava/import/shoes")

    async def async_import_strava_bikes(self) -> None:
        """Import bikes from Strava export data."""
        await self._request_json("post", "/api/v1/strava/import/bikes")

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> Any:
        """Perform an API request and parse the response body."""
        response = await self._raw_request(
            method,
            path,
            params=params,
            auth=auth,
            retry_on_auth=True,
        )
        body = await self._decode_response(response)
        if response.status == 429:
            raise EndurainRateLimitError(
                self._extract_error_message(body, "Rate limit exceeded"),
                retry_after=self._extract_retry_after(body),
            )
        if response.status == 401:
            raise EndurainAuthError("Authentication failed")
        if response.status < 200 or response.status >= 300:
            raise EndurainApiError(self._extract_error_message(body, f"Request failed: {path}"))
        return body

    async def _raw_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        auth: bool = True,
        retry_on_auth: bool = True,
    ) -> aiohttp.ClientResponse:
        """Execute a raw request against the API."""
        request_headers = {"Accept": "application/json"}
        if headers:
            request_headers.update(headers)

        if auth:
            if self._access_token is None:
                await self.async_login()
            request_headers["Authorization"] = f"Bearer {self._access_token}"
            request_headers.setdefault("X-Client-Type", "mobile")

        try:
            response = await self._session.request(
                method.upper(),
                f"{self._base_url}{path}",
                params=params,
                data=data,
                json=json_data,
                headers=request_headers,
                timeout=aiohttp.ClientTimeout(total=30),
            )
        except aiohttp.ClientError as err:
            raise EndurainApiError(f"Request failed: {err}") from err

        if auth and retry_on_auth and response.status == 401:
            response.release()
            self._access_token = None
            await self.async_login()
            request_headers["Authorization"] = f"Bearer {self._access_token}"
            try:
                response = await self._session.request(
                    method.upper(),
                    f"{self._base_url}{path}",
                    params=params,
                    data=data,
                    json=json_data,
                    headers=request_headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                )
            except aiohttp.ClientError as err:
                raise EndurainApiError(f"Request failed: {err}") from err

        return response

    async def _decode_response(self, response: aiohttp.ClientResponse) -> Any:
        """Decode a response body."""
        text = await response.text()
        if not text:
            return None
        content_type = response.headers.get("Content-Type", "")
        if "html" in content_type.lower() or "<!DOCTYPE html" in text or "<html" in text:
            raise EndurainApiError("Unexpected HTML response from Endurain")
        if "json" in content_type.lower():
            try:
                return json.loads(text)
            except json.JSONDecodeError as err:
                raise EndurainApiError("Invalid JSON response from Endurain") from err
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def _extract_error_message(self, body: Any, default: str) -> str:
        """Extract an error message from an API response."""
        if isinstance(body, Mapping):
            detail = body.get("detail") or body.get("error") or body.get("message")
            if detail:
                return str(detail)
        if isinstance(body, str) and body:
            return body
        return default

    def _extract_retry_after(self, body: Any) -> int | None:
        """Extract retry_after from an API response."""
        if isinstance(body, Mapping):
            value = body.get("retry_after")
            if isinstance(value, int):
                return value
        return None

    def _latest_record(
        self,
        payload: Any,
        *,
        primary_key: str,
        secondary_key: str | None = None,
    ) -> dict[str, Any] | None:
        """Return the most recent record from a paginated list payload."""
        if not isinstance(payload, Mapping):
            raise EndurainApiError("Unexpected list payload")
        records = payload.get("records")
        if not isinstance(records, list) or not records:
            return None

        def sort_key(item: Any) -> tuple[str, str]:
            if not isinstance(item, Mapping):
                return ("", "")
            primary = str(item.get(primary_key) or "")
            secondary = str(item.get(secondary_key) or "") if secondary_key else ""
            return (primary, secondary)

        latest = max(records, key=sort_key)
        if not isinstance(latest, Mapping):
            return None
        return dict(latest)

    def _build_gear_stats(
        self,
        gear: dict[str, Any],
        activities: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Combine gear metadata with activity usage statistics."""
        total_distance_m = sum(
            int(activity.get("distance") or 0)
            for activity in activities
            if isinstance(activity.get("distance"), int | float)
        )
        total_duration_s = sum(
            float(activity.get("total_timer_time") or activity.get("total_elapsed_time") or 0)
            for activity in activities
        )
        last_activity: dict[str, Any] | None = None
        if activities:
            last_activity = max(
                activities,
                key=lambda item: str(
                    item.get("start_time_tz_applied")
                    or item.get("start_time")
                    or item.get("created_at_tz_applied")
                    or item.get("created_at")
                    or ""
                ),
            )

        return {
            **gear,
            "activity_count": len(activities),
            "total_distance_km": round(total_distance_m / 1000, 2),
            "total_duration_hours": round(total_duration_s / 3600, 2),
            "average_distance_km": round((total_distance_m / 1000) / len(activities), 2)
            if activities
            else 0.0,
            "last_activity": last_activity,
            "last_activity_at": (
                last_activity.get("start_time_tz_applied")
                or last_activity.get("start_time")
                or last_activity.get("created_at_tz_applied")
                or last_activity.get("created_at")
            )
            if last_activity
            else None,
        }
