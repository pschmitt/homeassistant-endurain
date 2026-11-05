# Endurain for Home Assistant

[![Open this integration in Home Assistant Marketplace](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=pschmitt&repository=homeassistant-endurain&category=integration)

`endurain` is a Home Assistant custom integration for the self-hosted fitness tracking service [Endurain](https://github.com/endurain-project/endurain).

It creates a single service device for your Endurain account and exposes:

- weekly, monthly, yearly, and lifetime distance summaries
- unread notification count
- latest steps, sleep, and weight metrics
- per-goal progress sensors
- per-gear distance sensors with usage metadata
- a `event.workout_uploaded` entity that fires when Endurain's latest activity changes
- button entities for refresh, bulk import, and Strava gear sync
- service actions for Strava and activity sync workflows

## Features

- UI-based setup with config flow
- reconfigure and reauth support
- coordinator-based polling
- diagnostics support
- repair issue creation on authentication failures
- dynamic entities for goals and gear
- an event entity for new workout uploads

## Install

Use the badge above to add this repository as a custom integration in Home
Assistant Marketplace (Home Assistant 2026.11 or later), then install it and
restart Home Assistant. On older versions, add the repository as a custom
integration in HACS. Go to **Settings → Devices & services → Add integration**,
select **Endurain**, and provide your Endurain server URL and account details.

## Services

- `endurain.sync_recent_strava`
- `endurain.sync_strava_gear`
- `endurain.refresh_activities`
- `endurain.import_strava_shoes` and `endurain.import_strava_bikes` accept `file_path` pointing to the matching CSV from a Strava export.

The API client supports Endurain v0.20's paginated activity endpoints and background refresh jobs.

## Licensing

This integration is licensed under GPL-3.0-or-later. See [`LICENSE`](LICENSE).

The included Endurain logos and icons are **not** covered by this repository's GPL license. They are upstream Endurain brand assets and remain the property of the Endurain project. See [`NOTICE.md`](NOTICE.md).
