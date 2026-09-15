# SPDX-License-Identifier: GPL-3.0-or-later
"""Independent synthetic melody benchmark for the real torchcrepe stage (no ASR)."""

import argparse
import json
import subprocess
import sys

import numpy as np
import soundfile as sf

from karapincho import config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reuse", action="store_true", help="Evaluate an existing pitch.npz without rerunning inference"
    )
    parser.add_argument("--backend", choices=("cpu", "mps"), default="cpu")
    args = parser.parse_args()
    folder = config.ROOT / ".cache" / "pitch-benchmark"
    folder.mkdir(parents=True, exist_ok=True)
    rate = 16000
    waveform = np.zeros(8 * rate, dtype=np.float32)
    notes = [(1, 2.5, 60), (3, 4.5, 64), (5, 6.5, 67)]
    for start, end, midi in notes:
        t = np.arange(round((end - start) * rate)) / rate
        hz = 440 * 2 ** ((midi - 69) / 12)
        signal = sum(np.sin(2 * np.pi * hz * harmonic * t) / harmonic for harmonic in range(1, 7))
        envelope = np.minimum(1, t / 0.08) * np.minimum(1, (end - start - t) / 0.08)
        waveform[round(start * rate) : round(end * rate)] = signal * envelope * 0.15
    sf.write(folder / "vocals.wav", waveform, rate)
    if not args.reuse or not (folder / "pitch.npz").exists():
        subprocess.run([sys.executable, "-m", "karapincho.stage", "pitch", str(folder), "--backend", args.backend], check=True)
    runtime = json.loads((folder / "pitch.json").read_text()).get("runtime", {"backend": "cpu"})
    if args.backend == "mps" and runtime["backend"] != "mps":
        raise RuntimeError("MPS was unavailable: this run did not exercise GPU inference")
    with np.load(folder / "pitch.npz") as track:
        errors = []
        reference_frames = 0
        for start, end, midi in notes:
            reference = (track["time"] >= start + 0.1) & (track["time"] < end - 0.1)
            reference_frames += int(reference.sum())
            selected = reference & (track["confidence"] >= 0.35)
            predicted = 69 + 12 * np.log2(track["hz"][selected] / 440)
            errors.extend(abs(predicted - midi) * 100)
        silence = (track["time"] < 0.8) | (track["time"] > 6.8)
        voiced = (track["confidence"] >= 0.35) & (track["energy"] > 0.001)
        if not errors:
            raise RuntimeError("Pitch benchmark failed: the model suppressed all voiced reference frames")
        result = {
            "backend": runtime["backend"],
            "fixture": "synthetic harmonic tones, C4/E4/G4; not human singing",
            "median_pitch_error_cents": float(np.median(errors)),
            "fraction_within_50_cents": float(np.mean(np.asarray(errors) < 50)),
            "false_voiced_silence_frames": int((voiced & silence).sum()),
            "evaluated_frames": len(errors),
            "voiced_reference_coverage": len(errors) / reference_frames,
        }
    (folder / "metrics.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    if (
        result["fraction_within_50_cents"] < 1.0
        or result["voiced_reference_coverage"] < 1.0
        or result["false_voiced_silence_frames"]
    ):
        raise RuntimeError("Pitch benchmark failed its accuracy, coverage, or silence check")


if __name__ == "__main__":
    main()
