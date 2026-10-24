# Security review — 24 October 2026

Karapincho's Python locks and npm lockfile were checked against live advisory databases following the October incident reports. Vendor disclosures were checked for applicability. Package audit results do not establish exploitability or prove the machine has never been compromised.

## Applied updates

| Component | Previous | Updated | Reason |
| --- | --- | --- | --- |
| Node.js runtime | 26.10.0 initially observed | 26.12.1 verified | October DNS, TLS, Brotli, and CA-store fixes |
| Vite | 6.4.3 | 6.4.5 | File access, editor invocation, and middleware advisories |
| source-map-js | 1.2.1 | 1.2.2 | Source-map denial of service |
| Brotli | 1.2.0 | 1.2.1 | CVE-2026-111497 decoder memory corruption |
| certifi | 2026.7.22 | 2026.10.23 | Remove trust in compromised emSign CA chain |
| pip | 26.2.1 | 26.2.2 | Update its separate vendored certificate bundle |
| aiohttp | 3.14.3 | 3.14.4 | Eight reported HTTP, cookie, and resource handling issues |
| filelock | 3.32.6 | 4.2.4 | Lock path and filesystem security issues |
| multidict | 6.8.0 | 6.9.1 | Reference leak |
| NLTK | 3.10.3 | 3.10.4 | Move outside the advisory's affected range; audit no longer flags it |
| OpenTelemetry | 1.44.0 | 1.45.1 | TraceState parsing denial of service; companion packages updated together |
| Pillow | 12.3.0 | 13.0.0 | Image parsing, memory safety, and resource handling fixes |
| setuptools | 84.0.0 | 84.1.0 | Legacy wheel installation code injection on Windows |
| urllib3 | 2.7.0 | 2.8.0 | Streaming and proxy TLS fixes |
| FFmpeg executable | imageio-ffmpeg's bundled 7.1 | Homebrew 9.0.2_1 | Replace the obsolete executable with the maintained release |
| PyAV | 18.1.0 / FFmpeg 8 libraries | 19.0.2 / FFmpeg 9 libraries | Update the independent libraries used for media inspection |

The old imageio-ffmpeg fallback was removed from project dependencies and the local environment. Setup installs a maintained FFmpeg executable, and runtime checks reject missing, outdated, or unidentified versions. Media inspection explicitly selects MOV/MP4 or Matroska/WebM demuxers, and inspection/transcoding of source files restricts protocols to local files and pipes. This blocks disguised network playlists; it does not fix native decoder memory bugs.

Setup, the launcher, and npm lifecycle scripts reject Node versions below the supported security floors: 22.23.4, 24.22.1, and 26.12.1. CI uses `.node-version` and macOS 15 for the maintained Homebrew media runtime. Python requirements now contain security floors, and Setup bootstraps pip from a SHA-256-pinned wheel before other dependency downloads. The pip fix is needed even after updating certifi.

## Remaining findings

**The Python dependency audit is not clean.** It decreased from 75 entries across 12 packages to 17 entries across two packages. Database aliases include duplicate entries; these numbers are not unique exploitable vulnerability counts. No ignore rules were introduced. Exact advisory IDs, aliases, and available fixed versions are in [the audit evidence](security/dependency-audit-2026-10-24.json).

- **torch 2.8.0 — eight entries.** These include CVE-2026-24747, where `weights_only=True` does not prevent malicious checkpoint execution, plus tensor memory safety and deserialization reports. Available fixes require newer PyTorch releases, with one listed at 2.13.0; one entry has no listed fixed version.
- **transformers 4.57.6 — nine entries.** These include unsafe checkpoint handling, model configuration/code-loading issues, and `save_pretrained` path traversal. Several fixes require Transformers 5.10 or newer; some database entries list no fixed version.

The latest published WhisperX release checked was **3.8.6**. Its published metadata requires `torch~=2.8.0`, `torchaudio~=2.8.0`, `torchvision~=0.23.0`, `torchcodec>=0.6,<0.8`, and `huggingface-hub<1`. Current Transformers 5 releases require a newer Hub. A compatible full AI upgrade therefore requires replacing or porting WhisperX and revalidating transcription/alignment. Installing incompatible packages with `--no-deps` would leave a broken dependency graph. These findings remain unresolved, rather than being suppressed or described as patched. Use trusted model artifacts only; pinned revisions reduce exposure but do not patch these libraries.

**Native FFmpeg issues also remain outside pip/npm audit coverage.** The latest stable 9.0.2 release is still reported affected by October issues including CVE-2026-107676, CVE-2026-107677, and CVE-2026-107678. In particular, crafted MP4 `pssh` boxes can cause stack exhaustion during inspection, including through PyAV. A version bump or protocol restriction does not fix that flaw. Processing occurs in worker subprocesses, which limits a crash's reach, but this is not an OS security sandbox. Further work requires upstream fixes/backports and native-library validation; these releases must not be described as free of known vulnerabilities.

PHP, Next.js, and LiteLLM were absent from the project's declared/locked dependencies and local Python inventory. No LiteLLM startup artifacts were found in this project's virtual environment. This was a project review, not a whole-machine forensic investigation or an audit of unrelated hosting accounts.

## Verification

- npm audit: zero findings after the updates.
- Python lock audit: 17 entries remain, as described above.
- `pip check`, Ruff, shell syntax, and release integrity checks pass.
- Final full Python suite: 308 passed with two upstream deprecation warnings. An additional Matroska regression added during that run also passed; the final targeted media/security suite passed all 23 tests. The 72 Playwright/browser accessibility tests passed against the updated frontend.
- Frontend production build and two Node security-version tests pass.
- Both certifi's bundle and pip's vendored bundle were checked for removal of `emSign ECC Root CA - G3`.

Reproduce dependency checks using a separate environment with pip-audit 2.10.1 installed:

```bash
pip-audit -r requirements-macos.lock -r requirements-gpu.lock --no-deps --disable-pip
npm audit --prefix frontend
```

The Python command currently exits nonzero because of the unresolved findings. The locks enumerate the pinned packages; `--no-deps` checks those versions without resolving/downloading the large model runtime. It does not audit bundled native libraries or unknown vulnerabilities.

## Sources

- [Node.js October 21 security release](https://nodejs.org/en/blog/vulnerability/october-2026-security-releases)
- [Python security team's eMudhra notice](https://discuss.python.org/t/information-for-python-users-regarding-emudhra-emsign-ca-certificate-security-incident/109576/1) and [pip 26.2.2 changelog](https://pip.pypa.io/en/stable/news/)
- [Vite file access advisory](https://github.com/advisories/GHSA-rq7h-c2jc-7f22) and [source-map-js advisory](https://github.com/advisories/GHSA-68fv-2mgg-jv7q)
- [Pillow 13 security release](https://pillow.readthedocs.io/en/stable/releasenotes/13.0.0.html)
- [PyTorch checkpoint advisory](https://github.com/pytorch/pytorch/security/advisories/GHSA-63cw-57p8-fm3p) and [Transformers path traversal advisory](https://github.com/advisories/GHSA-xrqw-3rrv-vx5w)
- [WhisperX 3.8.6 published metadata](https://pypi.org/pypi/whisperx/3.8.6/json)
- [FFmpeg maintained releases](https://ffmpeg.org/download.html), [FFmpeg CVE-2026-107678](https://github.com/advisories/GHSA-rp4v-7m3g-89vg), and [FFmpeg source security tracker](https://security-tracker.debian.org/tracker/source-package/ffmpeg)
- [LiteLLM incident notice](https://docs.litellm.ai/blog/security-incident-oct-21-2026)
