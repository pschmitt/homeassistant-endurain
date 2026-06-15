# Endurain for Home Assistant

`endurain` is a Home Assistant custom integration for the self-hosted fitness tracking service [Endurain](https://github.com/endurain-project/endurain).

It creates a single service device for your Endurain account and exposes:

- weekly, monthly, yearly, and lifetime distance summaries
- unread notification count
- latest steps, sleep, and weight metrics
- per-goal progress sensors
- per-gear distance sensors with usage metadata
- a `event.workout_uploaded` entity that fires when Endurain's latest activity changes
- button entities for refresh, bulk import, Strava gear sync, and Strava bike/shoe imports
- service actions for Strava and activity sync workflows

## Features

- UI-based setup with config flow
- reconfigure and reauth support
- coordinator-based polling
- diagnostics support
- repair issue creation on authentication failures
- dynamic entities for goals and gear
- an event entity for new workout uploads

## Services

- `endurain.sync_recent_strava`
- `endurain.sync_strava_gear`
- `endurain.refresh_activities`

## Licensing

This integration is licensed under GPL-3.0-or-later. See [`LICENSE`](LICENSE).

The included Endurain logos and icons are **not** covered by this repository's GPL license. They are upstream Endurain brand assets and remain the property of the Endurain project. See [`NOTICE.md`](NOTICE.md).
