# SPDX-License-Identifier: GPL-3.0-or-later
"""Capability selection for isolated stages; never import AI runtimes in the server."""

import importlib.metadata
import importlib.util
import os
import platform
from dataclasses import asdict, dataclass

GIB = 1024**3
AI_STAGES = {"separate", "transcribe", "align", "pitch"}
# Promoted only after real fixture quality comparisons. CLI --backend bypasses this for validation.
VALIDATED = {"prepare", "separate", "transcribe", "align", "pitch"}
MLX_MODEL = "mlx-community/whisper-medium-mlx"
MLX_REVISION = "7fc08c4eac4c316526498f147dfdee6f6303f975"


@dataclass
class Runtime:
    architecture: str = platform.machine()
    os_version: str = platform.mac_ver()[0] or platform.release()
    backend: str = "cpu"
    selected_backend: str = "cpu"
    physical_bytes: int = 0
    available_bytes: int = 0
    batch_size: int = 16
    memory_limit_bytes: int = 0
    memory_limit_enforced: bool = False
    reduced: bool = False
    reason: str = ""

    def report(self):
        result = asdict(self)
        if self.backend == "mps":
            import torch
            torch.mps.synchronize()
            result["accelerator_current_bytes"] = torch.mps.current_allocated_memory()
            result["accelerator_driver_bytes"] = torch.mps.driver_allocated_memory()
        elif self.backend == "mlx":
            import mlx.core as mx
            mx.synchronize()
            result["accelerator_peak_bytes"] = mx.get_peak_memory()
        return result


CURRENT = Runtime()


def profile(total, available, reduced=False):
    batch = 8 if total < 12 * GIB else 16 if total < 24 * GIB else 32
    pressure = available < max(2 * GIB, total // 4)
    if pressure or reduced:
        batch = max(4, batch // 2)
    # macOS can reclaim file caches; reserve half of physical RAM for the system.
    # Under severe pressure avoid launching a GPU model at all.
    limit = total // 2 if available >= GIB else 0
    return batch, limit


def cpu_runtime(runtime):
    # Preserve the established CPU/Viterbi batch size; GPU profiles tune inference only.
    runtime.batch_size = 4 if runtime.reduced else 16
    return runtime


def configure(stage, reduced=False, backend=None):
    global CURRENT
    mode = os.environ.get("KARAPINCHO_ACCELERATION", "auto")
    if mode not in ("auto", "cpu"):
        raise ValueError("KARAPINCHO_ACCELERATION must be auto or cpu")
    import psutil
    memory = psutil.virtual_memory()
    batch, limit = profile(memory.total, memory.available, reduced)
    runtime = Runtime(physical_bytes=memory.total, available_bytes=memory.available,
                      batch_size=batch, memory_limit_bytes=limit, reduced=reduced)
    CURRENT = runtime
    if stage not in AI_STAGES | {"prepare"}:
        return cpu_runtime(runtime)
    desired = "mlx" if stage == "transcribe" else "videotoolbox" if stage == "prepare" else "mps"
    runtime.selected_backend = backend or (desired if mode == "auto" else "cpu")
    if backend == "cpu" or (backend is None and mode == "cpu"):
        return cpu_runtime(runtime)
    if backend and backend != desired:
        raise ValueError(f"Backend {backend} does not support {stage}")
    if backend is None and stage not in VALIDATED:
        runtime.reason = "Accelerated backend awaits fixture quality validation"
        return cpu_runtime(runtime)
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        runtime.reason = "Apple Silicon unavailable"
        return cpu_runtime(runtime)
    if desired != "videotoolbox" and limit < GIB:
        runtime.reason = "Insufficient available memory for acceleration"
        return cpu_runtime(runtime)
    if desired == "mps":
        import torch
        if not torch.backends.mps.is_available():
            runtime.reason = "MPS unavailable"
            return cpu_runtime(runtime)
        runtime.backend = desired
        recommended = torch.mps.recommended_max_memory()
        runtime.memory_limit_bytes = min(limit, recommended)
        torch.mps.set_per_process_memory_fraction(runtime.memory_limit_bytes / recommended)
        runtime.memory_limit_enforced = True
    elif desired == "mlx":
        if importlib.util.find_spec("mlx_whisper") is None:
            runtime.reason = "Optional MLX dependency unavailable"
            return cpu_runtime(runtime)
        if os.environ.get("KARAPINCHO_WHISPER_MODEL", "medium") != "medium":
            runtime.reason = "Custom Whisper model uses the CPU backend"
            return cpu_runtime(runtime)
        from .transcription import model_path
        try:
            model_path()
        except (OSError, ValueError):
            runtime.reason = "Pinned MLX model not cached; run Setup to download it"
            return cpu_runtime(runtime)
        try:
            import mlx.core as mx
        except (ImportError, OSError):
            runtime.reason = "Optional MLX runtime could not load"
            return cpu_runtime(runtime)
        if not mx.metal.is_available():
            runtime.reason = "MLX Metal unavailable"
            return cpu_runtime(runtime)
        runtime.backend = desired
        recommended = mx.device_info()["max_recommended_working_set_size"]
        runtime.memory_limit_bytes = min(limit, recommended)
        mx.set_memory_limit(runtime.memory_limit_bytes)
        runtime.memory_limit_enforced = True
        mx.set_cache_limit(0 if reduced else min(256 * 1024**2, runtime.memory_limit_bytes // 8))
    else:
        import subprocess
        from .config import ffmpeg
        probe = subprocess.run([ffmpeg(), "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=10)
        if "h264_videotoolbox" not in probe.stdout:
            runtime.reason = "VideoToolbox encoder unavailable"
            return cpu_runtime(runtime)
    runtime.backend = desired
    return runtime


def failure_kind(message, backend="cpu", returncode=1):
    message = message.lower()
    if returncode in (-9, -6) or any(s in message for s in ("out of memory", "cannot allocate", "memoryerror", "bad_alloc", "failed to allocate")):
        return "memory"
    if backend != "cpu" and any(s in message for s in (
        "notimplementederror", "not implemented for", "not currently implemented", "not supported", "unsupported",
        "mps backend", "mps device", "metal device", "command buffer execution failed", "videotoolbox", "hardware accelerator", "quality retry",
    )):
        return "backend"
    return "application"


def provenance(stage):
    names = {"transcribe": ("faster-whisper", "mlx-whisper", "mlx"),
             "separate": ("torch", "demucs"), "align": ("torch", "whisperx"),
             "pitch": ("torch", "torchcrepe")}.get(stage, ())
    versions = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return {"revision": 3, "mode": os.environ.get("KARAPINCHO_ACCELERATION", "auto"),
            "validated": stage in VALIDATED, "versions": versions,
            "model_revision": MLX_REVISION if stage == "transcribe" else "packaged-model",
            "whisper_model": os.environ.get("KARAPINCHO_WHISPER_MODEL", "medium") if stage == "transcribe" else None}
