# SPDX-License-Identifier: GPL-3.0-or-later
"""Score completed runs or compare them; references are read only after inference."""

import argparse
import json
from pathlib import Path

from karapincho.lyric_accuracy import release_gate
from karapincho.media import read_json, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = release_gate(read_json(args.before), read_json(args.after))
    write_json(args.output, result)
    print(json.dumps(result, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
