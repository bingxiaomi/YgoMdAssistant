"""Native HWND verification: cover MD with an opaque window, minimize, restore.

Never changes game resolution or performs duel actions. Saves only game frames
and a generated magenta occluder as local verification evidence.
"""
import ctypes
import json
import os
import sys
import time
from pathlib import Path
from ctypes import wintypes

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.pop("QT_QPA_PLATFORM", None)

from ygo_assistant.capture.windows import client_rect, enable_dpi_awareness, list_windows, user32
enable_dpi_awareness()

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QWidget

from ygo_assistant.capture.dxcam_capture import DXcamCapture
from ygo_assistant.capture.frame_pipeline import FramePipeline
from ygo_assistant.capture.snapshot import save_snapshot
from ygo_assistant.capture.wgc_capture import WGCCapture
from ygo_assistant.vision.region_manager import load_profile


def main():
    matches = [w for w in list_windows() if "masterduel" in "".join(w.title.lower().split())]
    if len(matches) != 1:
        raise SystemExit("Open exactly one MD window")
    game = matches[0]
    api = user32()
    api.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    api.ShowWindow(game.hwnd, 9)
    left, top, right, bottom = client_rect(game.hwnd)
    native_size = (right - left, bottom - top)
    output = ROOT / "data/captures/wgc_verification"
    output.mkdir(parents=True, exist_ok=True)
    profile = load_profile(ROOT / "configs/regions.yaml")
    app = QApplication([])
    cover = QWidget()
    cover.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
    cover.setStyleSheet("background-color: rgb(255,0,255)")
    cover.setGeometry(left, top, right - left, bottom - top)
    cover.setWindowTitle("Generated WGC occlusion verification")
    pipeline = FramePipeline(lambda: WGCCapture(game.hwnd), live=True)
    report = dict(window=vars(game), expected_native_size=list(native_size))
    stage = "baseline"
    samples = {}
    exit_code = 1
    timer = QTimer()

    def tick():
        frame = pipeline.frames.latest()
        if frame is not None:
            samples.setdefault(stage, []).append(frame)

    timer.timeout.connect(tick)
    timer.start(40)

    def magenta_ratio(image):
        return float(np.mean((image[:, :, 0] > 245) & (image[:, :, 1] < 10) & (image[:, :, 2] > 245)))

    def covered():
        nonlocal stage
        stage = "covered"
        samples.clear()
        cover.show()
        cover.raise_()
        cover.activateWindow()

    def verify_covered():
        nonlocal stage
        try:
            assert pipeline.status.error is None, pipeline.status.error
            frames = samples.get("covered", [])
            assert len(frames) > 3, "No new native frames while covered"
            frame = frames[-1]
            assert (frame.width, frame.height) == native_size
            desktop = DXcamCapture(game.hwnd)
            try:
                visible = desktop.read()
                assert visible is not None
                assert magenta_ratio(visible.image) > .95, "Generated window did not actually cover the game"
                save_snapshot(visible, profile, output / "desktop_occluded")
            finally:
                desktop.close()
            assert magenta_ratio(frame.image) < .05, "WGC received desktop occlusion instead of the HWND"
            assert float(np.std(frame.image)) > 5, "WGC returned a black/empty frame"
            save_snapshot(frame, profile, output / "native_covered")
            report.update(covered_frame_count=len(frames), captured_size=[frame.width, frame.height],
                          desktop_magenta_ratio=magenta_ratio(visible.image),
                          native_magenta_ratio=magenta_ratio(frame.image),
                          native_pixel_std=float(np.std(frame.image)),
                          source_pts_monotonic=all(a.source_timestamp_100ns < b.source_timestamp_100ns
                                                   for a, b in zip(frames, frames[1:])))
            cover.hide()
            stage = "minimized"
            samples.clear()
            api.ShowWindow(game.hwnd, 6)
            # Discard already-queued frames captured before the minimize request.
            QTimer.singleShot(250, lambda: samples.pop("minimized", None))
            QTimer.singleShot(1300, verify_minimized)
        except Exception as exc:
            report["error"] = repr(exc)
            finish()

    def verify_minimized():
        nonlocal stage
        try:
            assert not samples.get("minimized"), "Minimized/cached frame escaped into dataset pipeline"
            assert "最小化" in pipeline.status.message
            assert pipeline.alive
            report["minimized_wait_without_stale_frames"] = True
            api.ShowWindow(game.hwnd, 9)
            stage = "restored"
            samples.clear()
            QTimer.singleShot(1500, verify_restored)
        except Exception as exc:
            report["error"] = repr(exc)
            finish()

    def verify_restored():
        nonlocal exit_code
        try:
            frames = samples.get("restored", [])
            assert frames, "No fresh frames after restore"
            assert (frames[-1].width, frames[-1].height) == native_size
            report["automatic_resume_native_size"] = True
            report["received"] = pipeline.status.received
            exit_code = 0
        except Exception as exc:
            report["error"] = repr(exc)
        finish()

    def finish():
        timer.stop()
        cover.hide()
        api.ShowWindow(game.hwnd, 9)
        pipeline.request_stop()
        if not pipeline.join(3):
            report["shutdown_error"] = "WGC did not stop within 3 seconds"
        # Release full-frame history before exiting; production keeps one pending frame.
        samples.clear()
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        app.exit(exit_code)

    pipeline.start()
    QTimer.singleShot(900, covered)
    QTimer.singleShot(2500, verify_covered)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
