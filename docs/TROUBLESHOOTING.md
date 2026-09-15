# Troubleshooting

## Setup does not open

Control-click `Setup.command`, choose **Open**, and confirm macOS's prompt. Karapincho v0.1 requires an Apple Silicon Mac, macOS 14 or newer, Python 3.12, Node.js 22+, at least 10 GB free for setup, and 20 GB free recommended for normal use.

## Setup reports that MLX is unavailable

MLX transcription is optional. Karapincho continues with its CPU transcription backend and may still use MPS or VideoToolbox for other stages. Update macOS and rerun setup to try again.

## The browser cannot reach Karapincho

Keep the `Start.command` Terminal window open and reload `http://127.0.0.1:8765`. Do not bind the server to a public interface.

## YouTube rejects a link

Only single public video URLs are supported. Playlists, live links, authentication, and browser cookies are intentionally unsupported. Download or obtain an MP4 lawfully and use **Upload video** instead.

## A song fails or looks inaccurate

Use **View report** for the exact failed stage and quality notices. Correct lyrics and rebuild, or retry a failed/cancelled job. Automatic transcription, alignment, romanization, and pitch detection are best-effort.

## Storage

The models use about 6 GB and the environment about 2 GB. Source video, uncompressed analysis audio, checkpoints, and exports require additional working space. Delete completed songs through the app to remove their associated files safely.
