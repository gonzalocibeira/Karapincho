# SPDX-License-Identifier: GPL-3.0-or-later
"""Decode every output frame and verify the unchanged playback timeline contract."""
import argparse
import json
from pathlib import Path

import av
from karapincho.media import read_json


def validate(folder):
    metadata = read_json(folder / 'prepare.json')['metadata']
    with av.open(str(folder / 'video.mp4')) as container:
        assert len(container.streams.video) == 1 and not container.streams.audio
        stream = container.streams.video[0]
        assert stream.codec_context.name == 'h264'
        assert stream.average_rate == 30
        assert stream.codec_context.width <= 1920
        times = []
        for frame in container.decode(video=0):
            assert frame.format.name == 'yuv420p'
            times.append(float(frame.pts * frame.time_base))
        assert times and abs(times[0]) < 1/30
        assert all(b > a for a, b in zip(times, times[1:]))
        assert abs(times[-1] + 1/30 - metadata['duration']) < .08
    return {'folder': str(folder), 'frames_decoded': len(times), 'video_end': times[-1] + 1/30,
            'audio_timeline_duration': metadata['duration'], 'passed': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('folders', nargs='+', type=Path)
    args = parser.parse_args()
    print(json.dumps([validate(folder) for folder in args.folders], indent=2))
