# Architecture and API

Karapincho is a single-user local FastAPI service with a React interface. The server binds to `127.0.0.1`, stores work in `data/`, and runs one queued song at a time. AI-heavy stages execute in fresh subprocess groups so cancellation terminates child processes and GPU-to-CPU recovery does not retain both models in memory.

## Pipeline

1. Acquire and validate a YouTube video or uploaded MP4.
2. Normalize media and create analysis audio, playback MP3/video, and a cover.
3. Find or accept lyrics, isolate vocals, transcribe, and force-align words.
4. Detect pitch and convert words into syllable/mora-sized UltraStar notes.
5. Validate and atomically publish a four-file song folder and ZIP.

Completed stages carry dependency fingerprints and atomic checkpoints. Failed attempts never publish partial playable output.

## HTTP API

Read `GET /api/health` for readiness, version, limits, and the per-session token. Send that token as `X-Karapincho-Token` for every mutating request. Cross-origin requests are rejected.

| Endpoint | Behavior |
|---|---|
| `GET /api/health` | Version, readiness, session token, stages, and limits |
| `POST /api/shutdown` | Stop processing and shut down locally |
| `POST /api/jobs/url` | Queue one public YouTube URL |
| `POST /api/jobs/upload` | Queue one multipart MP4 upload |
| `GET /api/jobs`, `GET /api/jobs/{id}` | History, status, progress, and warnings |
| `POST /api/jobs/{id}/cancel` | Cancel queued or active work |
| `POST /api/jobs/{id}/retry` | Resume from valid checkpoints |
| `POST /api/jobs/{id}/rebuild` | Replace lyric settings and rebuild |
| `DELETE /api/jobs/{id}` | Delete the selected song and associated data |
| `GET /api/jobs/{id}/download` | Download a completed ZIP |
| `GET /api/jobs/{id}/report` | Download diagnostics |
| `POST /api/jobs/{id}/open-folder` | Open the local output folder |

The app is not a hosted multi-user service. Public binding, authentication proxies, and remote access are unsupported.
