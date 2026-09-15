# SPDX-License-Identifier: GPL-3.0-or-later
from karapincho import config
from karapincho.models import japanese_alignment_path, manifest, whisper_path


def test_model_manifest_has_pinned_release_sources():
    models = manifest()
    assert len(models) >= 8
    assert all(model["repository"] and model["revision"] and model["license"] for model in models)
    huggingface = [model for model in models if model["source"] == "huggingface"]
    assert all(len(model["revision"]) == 40 for model in huggingface)


def test_model_paths_use_immutable_revisions(tmp_path, monkeypatch):
    calls = []

    def snapshot_download(**kwargs):
        calls.append(kwargs)
        return tmp_path / kwargs["revision"]

    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr("huggingface_hub.snapshot_download", snapshot_download)
    assert whisper_path("medium").name == "08e178d48790749d25932bbc082711ddcfdfbc4f"
    assert whisper_path("small").name == "536b0662742c02347bc0e980a01041f333bce120"
    assert japanese_alignment_path().name == "cf031e020336460d15a417eba710bbc5bb43be9a"
    assert all(call["local_files_only"] is True for call in calls)
