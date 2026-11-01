# Agent instructions

## Project

This Home Assistant integration connects to the self-hosted Endurain fitness service and exposes activity summaries, goals, gear, and related account data as entities and actions.

## Working in this repository

- Read `README.md` before changing API behavior, available entities, or sync actions; it documents the supported Endurain API behavior and service names.
- Keep dynamic goal and gear entities, refresh behavior, and activity imports consistent with the documented integration behavior.
- Before changing CI, check [pschmitt/ci-workflows](https://github.com/pschmitt/ci-workflows) for reusable components and preserve this repository's existing checks.

## Validation

- Run `uvx ruff check .` and `uvx ruff format --check .` for Python changes.
- CI runs Hassfest and the shared Ruff checks; it currently has no test job.
