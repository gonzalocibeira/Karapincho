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

## Creation workflow and handoff

Quality is the default for new and migrated jobs. Fast uses the bundled small CPU Whisper model with beam size 1; separation, alignment, pitch, and chart validation retain the Quality pipeline. Processing mode is persisted per job. Its transcription fingerprint invalidates transcription and downstream stages while retaining prepared media and pitch. The 8 GB automatic profile starts transcription on CPU to avoid speculative MLX passes followed by complete CPU retries; explicit backend overrides remain available for benchmarks.

The interface loads active work plus 20 recent jobs at a time. Refreshes cannot overlap: two seconds during processing, fifteen seconds while idle, and suspended when hidden. Timers belong to active job cards; unchanged job cards retain their data references.

| Endpoint | Behavior |
|---|---|
| `GET /api/jobs/feed?limit=20&before=<job-id>` | Active queue plus a bounded recent-history page and continuation ID |
| `GET /api/settings` | Saved karaoke Songs folder |
| `POST /api/settings/choose-folder` | Native macOS folder picker; cancellation retains the prior folder |
| `POST /api/jobs/{id}/export` | Copy validated package; `collision` is `ask` (default), `keep_both`, or `replace` |
| `GET /api/jobs/{id}/cleanup` | Reclaimable local bytes |
| `POST /api/jobs/{id}/cleanup` | Remove local job/package files, retaining export receipt and history |
| `POST /api/jobs/{id}/processing-mode` | Queue a stopped job in `quality` or `fast` mode |

Creation accepts `processing_mode` in URL JSON or upload form data; omission means Quality. Existing ZIP, retry, and lyric-rebuild request formats remain supported. Cleaned jobs cannot retry or rebuild. They remain visible through the feed and individual job endpoint.

Export state is independent of processing status. Copies stage on the destination volume, validate and hash all four files, then publish atomically. macOS publication uses an exclusive rename so another app cannot have its newly created directory overwritten. Explicit replacement retains a rollback copy. A local publication journal recovers interrupted renames on the next export or cleanup. If an external edit prevents safe recovery, the backup remains available and the API reports its location. Hash-matching exports are idempotent; external edits cause a fresh collision decision. Cleanup never follows links into external song copies.

Pitch inference uses batches of 16 on an 8 GB Mac when at least 2 GB is available; memory-pressure and recovery paths retain smaller batches and the enforced GPU memory cap. Viterbi decoding stays in the same 16-frame groups.

Stage reports include model-loading seconds, stage and attempt elapsed time, and peak resident memory. These are local diagnostics; no telemetry is sent.
