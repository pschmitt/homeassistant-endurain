"""API client for Endurain."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
from collections.abc import Callable, Mapping
from datetime import date, timedelta
from pathlib import Path
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
        device_id: str | None = None,
        on_device_id: Callable[[str], None] | None = None,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._mfa_code = mfa_code
        self._device_id = device_id
        self._on_device_id = on_device_id
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

            code_verifier = secrets.token_urlsafe(64)
            code_challenge = (
                base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
                .rstrip(b"=")
                .decode()
            )
            payload = {
                "username": self._username,
                "password": self._password,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
            response = await self._raw_request(
                "post",
                "/api/v1/auth/login",
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    **self._auth_headers(),
                },
                data=payload,
                auth=False,
                retry_on_auth=False,
            )
            body = await self._decode_auth_response(response, "Login failed", loop)

            if body.get("next_step") == "mfa":
                code = mfa_code or self._mfa_code
                if not code:
                    raise EndurainMfaRequiredError("MFA is required")
                body = await self.async_verify_mfa(str(body.get("mfa_challenge") or ""), code)

            if body.get("next_step") == "password_change":
                raise EndurainAuthError(
                    "Endurain requires a password change; sign in to Endurain and change it"
                )

            if body.get("next_step") == "exchange":
                self._store_device_id(body.get("device_id"))
                session_id = body.get("session_id")
                if not session_id:
                    raise EndurainAuthError("Login response missing session id")
                response = await self._raw_request(
                    "post",
                    f"/api/v1/auth/sessions/{session_id}/tokens",
                    headers={"Content-Type": "application/json", **self._auth_headers()},
                    json_data={"code_verifier": code_verifier},
                    auth=False,
                    retry_on_auth=False,
                )
                body = await self._decode_auth_response(response, "Token exchange failed", loop)

            if body.get("next_step") != "tokens":
                raise EndurainAuthError(
                    f"Unsupported Endurain sign-in step: {body.get('next_step')}"
                )
            if not body.get("access_token"):
                raise EndurainAuthError("Login response missing access token")

            self._store_device_id(body.get("device_id"))
            self._login_retry_at = 0.0
            self._access_token = str(body["access_token"])
            return self._access_token

    def _auth_headers(self) -> dict[str, str]:
        """Return the headers every mobile /auth/ request carries."""
        headers = {"X-Client-Type": "mobile"}
        if self._device_id:
            headers["X-Device-Id"] = self._device_id
        return headers

    def _store_device_id(self, device_id: Any) -> None:
        """Remember the device id so later sign-ins are not reported as new devices."""
        if not isinstance(device_id, str) or not device_id or device_id == self._device_id:
            return
        self._device_id = device_id
        if self._on_device_id is not None:
            self._on_device_id(device_id)

    async def _decode_auth_response(
        self,
        response: aiohttp.ClientResponse,
        default_error: str,
        loop: asyncio.AbstractEventLoop,
    ) -> dict[str, Any]:
        """Decode a sign-in step answer, mapping failures to integration errors."""
        body = await self._decode_response(response)
        if response.status == 429:
            retry_after = self._extract_retry_after(body) or 60
            self._login_retry_at = loop.time() + retry_after
            raise EndurainRateLimitError(
                self._extract_error_message(body, "Rate limit exceeded"),
                retry_after=retry_after,
            )
        if response.status >= 500:
            raise EndurainApiError(
                self._extract_error_message(
                    body, f"{default_error}: server error {response.status}"
                )
            )
        if response.status < 200 or response.status >= 300:
            raise EndurainAuthError(self._extract_error_message(body, default_error))
        if not isinstance(body, Mapping):
            raise EndurainAuthError(f"{default_error}: response was not JSON")
        return dict(body)

    async def async_verify_mfa(self, mfa_challenge: str, code: str) -> dict[str, Any]:
        """Answer the MFA step of a sign-in."""
        response = await self._raw_request(
            "post",
            "/api/v1/auth/mfa/verify",
            headers={"Content-Type": "application/json", **self._auth_headers()},
            json_data={"mfa_challenge": mfa_challenge, "mfa_code": code},
            auth=False,
            retry_on_auth=False,
        )
        body = await self._decode_auth_response(
            response, "MFA verification failed", asyncio.get_running_loop()
        )
        self._mfa_code = code
        return body

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
        data = await self._request_json(
            "get",
            "/api/v1/activities/summaries",
            params={"period": view_type},
        )
        if not isinstance(data, Mapping):
            raise EndurainApiError(f"Unexpected {view_type} summary payload")
        return dict(data)

    async def async_fetch_goals_progress(self) -> list[dict[str, Any]]:
        """Fetch goal progress."""
        return await self._fetch_all_pages("/api/v1/profile/goals/results", page_size=100)

    async def async_fetch_latest_activity(self, user_id: str) -> dict[str, Any] | None:
        """Fetch the most recent activity for the configured user."""
        activities = await self._fetch_all_pages(
            f"/api/v1/users/{user_id}/activities",
            page_size=1,
            limit=1,
        )
        return activities[0] if activities else None

    async def async_fetch_recent_activities(
        self, user_id: str, num_records: int = 400
    ) -> list[dict[str, Any]]:
        """Fetch the most recent activities for the configured user."""
        return await self._fetch_all_pages(
            f"/api/v1/users/{user_id}/activities",
            page_size=200,
            limit=num_records,
        )

    async def async_fetch_activity_streams(self, activity_id: str) -> list[dict[str, Any]]:
        """Fetch all activity streams for the given activity."""
        return await self._fetch_all_pages(
            f"/api/v1/activities/{activity_id}/streams",
            page_size=200,
        )

    async def async_fetch_activity_laps(self, activity_id: str) -> list[dict[str, Any]]:
        """Fetch all laps for the given activity."""
        return await self._fetch_all_pages(
            f"/api/v1/activities/{activity_id}/laps",
            page_size=200,
        )

    async def async_fetch_notifications_number(self) -> int:
        """Fetch the unread notifications count."""
        data = await self._request_json("get", "/api/v1/notifications/unread-count")
        if isinstance(data, Mapping) and isinstance(data.get("count"), int):
            return data["count"]
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
        if isinstance(gears, Mapping):
            gears = gears.get("items")
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
                activities = await self._fetch_all_pages(
                    "/api/v1/activities",
                    page_size=200,
                    params={"gear_id": gear_id},
                )
            enriched.append(self._build_gear_stats(gear_dict, activities))
        return enriched

    async def async_sync_recent_strava(self, days: int) -> None:
        """Trigger a Strava activity sync for the last N days."""
        start_date = date.today() - timedelta(days=days)
        end_date = date.today()
        await self._request_json(
            "post",
            "/api/v1/strava/activities",
            params={
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            },
        )

    async def async_sync_strava_gear(self) -> None:
        """Trigger a Strava gear sync."""
        await self._request_json("post", "/api/v1/strava/gear")

    async def async_refresh_activities(self) -> None:
        """Trigger an activity refresh."""
        await self._request_json("post", "/api/v1/activities/refresh")

    async def async_bulk_import(self) -> None:
        """Trigger Endurain's bulk import pipeline."""
        await self._request_json("post", "/api/v1/activities/bulk-import/folder")

    async def _fetch_all_pages(
        self,
        path: str,
        *,
        page_size: int,
        limit: int | None = None,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch every page from an Endurain paginated endpoint."""
        records: list[dict[str, Any]] = []
        page_number = 1
        while limit is None or len(records) < limit:
            data = await self._request_json(
                "get",
                path,
                params={**(params or {}), "page_number": page_number, "num_records": page_size},
            )
            if not isinstance(data, Mapping):
                raise EndurainApiError("Unexpected paginated response")
            items = data.get("items")
            if not isinstance(items, list):
                raise EndurainApiError("Paginated response is missing items")

            records.extend(dict(item) for item in items if isinstance(item, Mapping))
            next_page = data.get("next")
            if next_page is None or not items:
                break
            if not isinstance(next_page, int) or next_page <= page_number:
                raise EndurainApiError("Invalid pagination cursor")
            page_number = next_page

        return records[:limit] if limit is not None else records

    async def async_import_strava_shoes(self, file_path: str) -> None:
        """Import shoes from Strava export data."""
        await self._async_import_strava_csv("shoes", file_path)

    async def async_import_strava_bikes(self, file_path: str) -> None:
        """Import bikes from Strava export data."""
        await self._async_import_strava_csv("bike", file_path)

    async def _async_import_strava_csv(self, gear_type: str, file_path: str) -> None:
        """Upload a Strava export CSV to Endurain."""
        path = Path(file_path)
        try:
            contents = await asyncio.to_thread(path.read_bytes)
        except OSError as err:
            raise EndurainApiError(f"Could not read Strava export file: {path}") from err

        await self._request_json(
            "post",
            "/api/v1/strava/import/gear",
            params={"gear_type": gear_type},
            data_factory=lambda: self._strava_csv_form(contents, path.name),
        )

    def _strava_csv_form(self, contents: bytes, filename: str) -> aiohttp.FormData:
        """Create a fresh multipart body for an uploaded Strava CSV."""
        form = aiohttp.FormData()
        form.add_field("file", contents, filename=filename, content_type="text/csv")
        return form

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        auth: bool = True,
        data: Any = None,
        data_factory: Callable[[], Any] | None = None,
    ) -> Any:
        """Perform an API request and parse the response body."""
        response = await self._raw_request(
            method,
            path,
            params=params,
            data=data,
            data_factory=data_factory,
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
        data: Any = None,
        data_factory: Callable[[], Any] | None = None,
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
                data=data_factory() if data_factory else data,
                json=json_data,
                headers=request_headers,
                timeout=aiohttp.ClientTimeout(total=30),
            )
        except (aiohttp.ClientError, TimeoutError) as err:
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
                    data=data_factory() if data_factory else data,
                    json=json_data,
                    headers=request_headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                )
            except (aiohttp.ClientError, TimeoutError) as err:
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
        records = payload.get("items")
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
