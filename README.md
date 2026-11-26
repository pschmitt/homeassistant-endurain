<p align="center">
  <img src="logo.png" width="128" alt="Endurain logo">
</p>

<p align="center">
  <a href="https://my.home-assistant.io/redirect/marketplace_repository/?owner=pschmitt&amp;repository=homeassistant-endurain&amp;category=integration"><img src="https://my.home-assistant.io/badges/marketplace_repository.svg" alt="Open this integration in Home Assistant Marketplace"></a>
</p>

<h1 align="center">Endurain for Home Assistant</h1>

<p align="center">Track activity summaries, goals and gear from a self-hosted Endurain account in Home Assistant.</p>

## Features

- **Activity summaries:** Show weekly, monthly, yearly and lifetime distance, plus recent steps, sleep and weight.
- **Goals and gear:** Create progress and distance sensors for each goal and piece of gear.
- **Workout events:** Emit a workout-uploaded event when the latest activity changes.
- **Account controls:** Refresh, bulk import and sync Strava gear with button entities and `endurain` actions.
- **Account recovery:** Reconfigure or reauthenticate through the UI; authentication failures raise repairs.

## Install

Use the Marketplace badge above on Home Assistant 2026.11 or later to add this
repository as a custom integration. On older versions, add it as a HACS
custom repository of type **Integration**. Install and restart Home Assistant.
The badge does not imply a public catalog listing.

## Quick start

1. In Endurain, create an API key under **Settings → Security → API keys** with
   the scopes `account`, `activities:read`, `activities:write`, `gears:read`,
   `gears:write`, `health:read` and `notifications:read`.
2. Go to **Settings → Devices & services → Add integration** and select **Endurain**.
3. Enter your [Endurain](https://github.com/endurain-project/endurain) server URL
   and the API key.
4. Open the Endurain device to inspect distance, notifications, goals and gear.

The integration requires Endurain v0.21 or later and authenticates only with
an API key. Endurain API keys expire (365 days by default): when the key stops
working, Home Assistant asks you to reauthenticate with a new one. Revoke the
old key in Endurain afterwards.

Entries set up with a username and password before API keys ask to
reauthenticate with a key.

Strava import actions take `file_path` for the matching CSV from a Strava
export.

## License

[GPL-3.0-or-later](LICENSE). The included Endurain logos and icons are upstream
brand assets, not covered by this license; see [NOTICE](NOTICE.md).
