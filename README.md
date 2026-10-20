# Downloads archiver (Podman Compose) v3

Rootless Podman Compose; no host pip or systemd timer. Cron runs in the container.

## Behavior

- Files and entire top-level folders are archived after **AGE_DAYS** days without observed change.
- Top-level files **larger** than `MAX_SIZE` are handled separately, **also only after AGE_DAYS**. `DELETE_LARGE=true` irreversibly deletes them; `DELETE_LARGE=false` moves them to GNOME's trash (`~/.local/share/Trash/files` and `info`).
- Folder size is unrestricted. Files *inside* an eligible folder are archived with the folder; they are **not** deleted or trashed for exceeding `MAX_SIZE`.
- `DRY_RUN=true` simulates all moves/deletions. It still updates first-seen records in `./state/seen.json`.
- Timestamp is first-observed/last-changed, not necessarily the real download time. First run starts a new aging window for existing files. Keep `state/` persistent.
- Trash is a bind mount of the **host user's** `~/.local/share/Trash` so GNOME Files can display it. `DOWNLOADS_DIR_HOST` is set by Compose, supplying the original file path for restore metadata.
- Names in trash get unique suffixes to prevent collisions. Cross-filesystem moves use copy-and-remove, not atomic rename; ensure enough free space. Deletion is permanent with `DELETE_LARGE=true`.
- Symlinks and special files are skipped. No monitoring of files arriving and disappearing between scans.
- No simultaneous runs; don't run `sim` while the service might already be scanning.

## Setup

Review `.env` paths and `archiver.env`. Create mount points:

```sh
mkdir -p "$HOME/Old-Downloads" "$HOME/.local/share/Trash/files" "$HOME/.local/share/Trash/info" state
podman compose build
podman compose run --rm archiver sim
podman compose up -d
podman compose logs -f
```

Default schedule: every five minutes. Default dry-run is **on**; set `DRY_RUN=false` and `podman compose up -d --force-recreate` after checking output. Use `podman compose down` to stop. Rootless `restart: unless-stopped` may not restart after host reboot without Podman/systemd support.

## Important

The project uses organize-tool for archiving while Python handles first-seen tracking and oversize trash/deletion. Python dependencies are installed **inside the image only**. The host remains unchanged.
