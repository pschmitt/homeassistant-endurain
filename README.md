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

1. Go to **Settings → Devices & services → Add integration** and select **Endurain**.
2. Enter your [Endurain](https://github.com/endurain-project/endurain) server URL
   and an API key (Endurain: **Settings → Security → API keys**). Or leave the
   key empty and sign in once with your username and password: the integration
   then creates a key named "Home Assistant" and does not store your password.
3. Open the Endurain device to inspect distance, notifications, goals and gear.

The integration requires Endurain v0.21 or later and authenticates with an API
key. A key the integration creates holds the scopes `account`, `activities:read`,
`activities:write`, `gears:read`, `gears:write`, `health:read` and
`notifications:read`; a key you create needs the same for every sensor and
action to work. Endurain API keys expire (365 days by default). Two weeks
before the key the integration created expires, Home Assistant asks you to
reauthenticate; signing in there creates a new key and revokes the old one.

Entries set up with a username and password before this version switch to an
API key on their own at the next start, unless the account uses MFA: those ask
to reauthenticate.

Strava import actions take `file_path` for the matching CSV from a Strava
export.

## License

[GPL-3.0-or-later](LICENSE). The included Endurain logos and icons are upstream
brand assets, not covered by this license; see [NOTICE](NOTICE.md).
