# SPDX-License-Identifier: GPL-3.0-or-later
"""Fast, offline checks for files that must be coherent in a public source release."""

import hashlib
import json
import re
import subprocess
from pathlib import Path

from karapincho import __version__

ROOT = Path(__file__).resolve().parents[1]


def main():
    frontend_package = json.loads((ROOT / "frontend/package.json").read_text())
    assert frontend_package["version"] == __version__, "Frontend and package versions differ"
    assert (ROOT / "LICENSE").read_text().lstrip().startswith("GNU GENERAL PUBLIC LICENSE")
    required = [
        "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "SECURITY.md", "SUPPORT.md",
        "VALIDATION.md", "docs/ARCHITECTURE.md", "docs/BENCHMARKS.md", "docs/PRIVACY.md",
        "docs/REFERENCES.md", "docs/RELEASE_NOTES_v0.1.0.md",
        "docs/assets/karapincho-logo.svg", "docs/assets/social-preview.svg",
        "docs/assets/social-preview.png", "docs/assets/screenshot-studio.png",
        ".github/release-assets.sha256",
    ]
    for relative in required:
        assert (ROOT / relative).is_file(), f"Missing release file: {relative}"

    manifest = json.loads((ROOT / "karapincho/model_manifest.json").read_text())
    assert manifest["schema"] == 1 and len(manifest["models"]) >= 8
    for model in manifest["models"]:
        assert all(model.get(key) for key in ("purpose", "repository", "provenance", "revision", "license"))

    readme = (ROOT / "README.md").read_text()
    assert "AI-assisted development" in readme and "GPL-3.0-or-later" in readme
    assert f"Version {__version__}" in readme
    assert (ROOT / "VALIDATION.md").read_text().startswith(f"# Karapincho v{__version__} validation")
    for target in re.findall(r"\[[^]]+\]\((?!https?://)([^)#]+)", readme):
        assert (ROOT / target).exists(), f"Broken README link: {target}"

    tracked = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
    banned = ("data/", ".cache/", ".venv/", "frontend/node_modules/", "frontend/dist/")
    assert not [path for path in tracked if path.startswith(banned)]

    release_files = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT, text=True,
    ).splitlines()
    source_suffixes = {
        ".py": "#", ".ts": "//", ".tsx": "//", ".mjs": "//", ".css": "/*",
        ".html": "<!--", ".command": "#", ".yml": "#",
    }
    for relative in release_files:
        path = ROOT / relative
        prefix = source_suffixes.get(path.suffix)
        if prefix:
            assert "SPDX-License-Identifier: GPL-3.0-or-later" in path.read_text()[:160], relative

    for line in (ROOT / ".github/release-assets.sha256").read_text().splitlines():
        expected, relative = line.split("  ", 1)
        actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert actual == expected, f"Release asset changed without updating hash: {relative}"
    print("Release integrity checks passed.")


if __name__ == "__main__":
    main()
