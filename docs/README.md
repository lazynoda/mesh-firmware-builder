# Mesh Firmware Builder Documentation

New here? Start with the [project README](../README.md).

## Running It

- [Local Development](local-development.md): run the app and a worker on your
  machine, with or without Docker.
- [Docker Compose Flow](compose-flow.md): step-by-step smoke test, fake and real
  builds, remote Docker daemons.
- [Operations](operations.md): deployment behind a reverse proxy, backups, logs,
  firmware version admin.
- [Configuration](configuration.md): every `MB_*` environment variable.
- [Firmware Sources](firmwares.md): the firmwares users can pick, in
  `data/firmwares.json`.

## How It Works

- [Architecture](architecture.md): the web, worker and builder split, and the
  request flow.
- [Worker and Builder](worker-and-builder.md): build lifecycle, the builder
  image, reading build logs, what goes into the ZIP.
- [userPrefs Support](userprefs-support.md): which firmware settings the form
  offers, and which it rejects and why.
- [Advanced Build Options](build-options.md): settings `userPrefs.jsonc` cannot
  express, and the two firmware patches.
- [Frontend](frontend.md): the static UI, translations, version gating.
- [API](api.md): HTTP endpoints.
- [Database](database.md): SQLite schema and queue semantics.

## Quality

- [Security Model](security.md): input validation, builder isolation, secrets.
- [Testing](testing.md): what the test suite covers.
- [Roadmap](roadmap.md): what is done and what comes next.

Working on the code with an AI agent? Read [AGENTS.md](../AGENTS.md) first.
