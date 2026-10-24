# Security policy

## Supported versions

Security fixes are provided for the latest tagged release only.

## Reporting a vulnerability

Please do not disclose a vulnerability in a public issue. Use GitHub's **Report a vulnerability** action on the repository Security page to submit it privately. Include reproduction steps, affected versions, and likely impact when possible.

Karapincho is a local single-user application and must remain bound to `127.0.0.1`. Running it on a public network interface is unsupported.

Use patched Node.js 22.23.4+, 24.22.1+, or 26.12.1+ within those release lines, pip 26.2.2+, certifi 2026.10.19+, and a maintained FFmpeg installation. Rerun `Setup.command` after security dependency updates; updating certifi alone does not update pip's separate certificate bundle.

The [24 October 2026 review](docs/SECURITY_REVIEW_2026-10-24.md) records the fixes and remaining upstream PyTorch, Transformers, and FFmpeg risks. The dependency audit is not currently clean. Model checkpoints must come from trusted sources; `weights_only=True` is not a security boundary on the required PyTorch 2.8 runtime.
