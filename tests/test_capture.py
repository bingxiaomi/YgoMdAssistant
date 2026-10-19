import json
import time

import cv2
import numpy as np
import pytest

from ygo_assistant.capture.base import Frame
from ygo_assistant.capture.frame_pipeline import FramePipeline, LatestFrames
from ygo_assistant.capture.snapshot import save_snapshot
from ygo_assistant.capture.video_capture import VideoCapture
from ygo_assistant.vision.region_manager import Region, default_profile, load_profile, save_profile


@pytest.fixture
def video_file(tmp_path):
    path = tmp_path / "test.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (80, 40))
    assert writer.isOpened()
    for i in range(12):
        writer.write(np.full((40, 80, 3), i * 20, dtype=np.uint8))
    writer.release()
    return path


def wait_frame(pipeline, expected=None):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        assert pipeline.status.error is None, pipeline.status.error
        frame = pipeline.frames.latest()
        if frame is not None and (expected is None or frame.frame_id == expected):
            return frame
        time.sleep(.005)
    raise AssertionError(f"Frame {expected} did not arrive")


def test_video_timestamps_seek_and_eof(video_file):
    source = VideoCapture(video_file)
    try:
        assert source.frame_count == 12
        first = source.read()
        second = source.read()
        assert first.frame_id == 0 and first.timestamp_ms == 0
        assert second.timestamp_ms == 100
        source.seek_frame(8)
        assert source.read().frame_id == 8
        source.seek_frame(11)
        assert source.read() is not None
        assert source.read() is None and source.ended
        source.seek_frame(0)
        assert not source.ended
        assert source.read().frame_id == 0
    finally:
        source.close()


def test_bad_video_does_not_crash(tmp_path):
    with pytest.raises(ValueError):
        VideoCapture(tmp_path / "missing.mp4")


def test_live_and_video_share_regions_and_roundtrip(tmp_path):
    profile = default_profile()
    image = np.arange(120 * 200 * 3, dtype=np.uint8).reshape(120, 200, 3)
    live = Frame(0, 1, image, "live_window", 200, 120)
    replay = Frame(0, 1, image, "video_file", 200, 120)
    save_profile(profile, tmp_path / "regions.yaml")
    restored = load_profile(tmp_path / "regions.yaml")
    for name, crop in restored.crops(live).items():
        assert np.array_equal(crop, restored.crops(replay)[name])
    left, top, right, bottom = Region(label="r", x=.5, y=.5, width=.5, height=.5).pixels(200, 120)
    assert (left, top, right, bottom) == (100, 60, 200, 120)
    with pytest.raises(ValueError):
        Region(label="r", x=.9, y=0, width=.2, height=1)


def test_bounded_queue_keeps_latest():
    queue = LatestFrames(2)
    image = np.zeros((2, 2, 3), np.uint8)
    for i in range(20):
        queue.put(Frame(i, i, image, "live_window", 2, 2))
    assert len(queue) == 2
    assert queue.latest().frame_id == 19
    assert queue.dropped == 19
    assert len(queue) == 0


def test_video_worker_pause_seek_play_and_stop(video_file):
    pipeline = FramePipeline(lambda: VideoCapture(video_file), live=False)
    pipeline.start()
    try:
        assert wait_frame(pipeline).frame_id == 0
        time.sleep(.03)
        assert pipeline.frames.latest() is None
        pipeline.seek_frame(5)
        assert wait_frame(pipeline, 5).timestamp_ms == 500
        pipeline.set_paused(False)
        assert wait_frame(pipeline).frame_id > 5
    finally:
        pipeline.request_stop()
        assert pipeline.join()


def test_source_failure_becomes_status():
    def fail():
        raise RuntimeError("window closed")
    pipeline = FramePipeline(fail, live=True)
    pipeline.start()
    assert pipeline.join()
    assert pipeline.status.error == "window closed"


def test_snapshot_preserves_raw_pixels_and_metadata(tmp_path):
    image = np.full((40, 80, 3), (10, 20, 30), np.uint8)
    target = save_snapshot(Frame(2, 123, image, "video_file", 80, 40), default_profile(), tmp_path)
    metadata = json.loads((target / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["timestamp_ms"] == 123
    assert set(metadata["files"]) == {"frame", "duel_log", "effect_text"}
    assert np.array_equal(cv2.imread(str(target / "frame.png")), image)
