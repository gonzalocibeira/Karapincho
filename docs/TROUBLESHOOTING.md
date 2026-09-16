# Troubleshooting

## Setup does not open

Control-click `Setup.command`, choose **Open**, and confirm macOS's prompt. Karapincho v0.1 requires an Apple Silicon Mac, macOS 14 or newer, Python 3.12, Node.js 22+, at least 10 GB free for setup, and 20 GB free recommended for normal use.

## Setup reports that MLX is unavailable

MLX transcription is optional. Karapincho continues with its CPU transcription backend and may still use MPS or VideoToolbox for other stages. Update macOS and rerun setup to try again.

## The browser cannot reach Karapincho

Keep the `Start.command` Terminal window open and reload `http://127.0.0.1:8765`. Do not bind the server to a public interface.

## YouTube rejects a link

Only single public video URLs are supported. Playlists, live links, authentication, and browser cookies are intentionally unsupported. Download or obtain an MP4 lawfully and use **Upload video** instead.

## Processing pauses when I leave my Mac

Karapincho automatically prevents macOS idle sleep while generating or rebuilding a song, and releases that protection when the job finishes, fails, or is cancelled. The display can still turn off, and the browser does not need to stay in the foreground. Your system sleep settings are not changed.

Keep a MacBook's lid open and leave the `Start.command` Terminal window running. Closing the lid, choosing **Sleep**, or running critically low on battery can still suspend processing. Connect power for long queues. If you updated Karapincho while it was running, quit and reopen it after the current work finishes to load the updated worker.

## A song fails or looks inaccurate

Use **View report** for the exact failed stage and quality notices. Correct lyrics and rebuild, or retry a failed/cancelled job. Automatic transcription, alignment, romanization, and pitch detection are best-effort.

## Storage

The models use about 6 GB and the environment about 2 GB. Source video, uncompressed analysis audio, checkpoints, and exports require additional working space. Delete completed songs through the app to remove their associated files safely.
