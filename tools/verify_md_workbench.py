"""Native end-to-end verification against an already-open MD replay.

--layout places the game and workbench side by side on a >=2560px desktop.
Only resizes/repositions the game window; never performs duel actions.
"""
import argparse
import ctypes
import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.pop("QT_QPA_PLATFORM", None)

from ygo_assistant.capture.windows import client_rect, enable_dpi_awareness, list_windows, user32
enable_dpi_awareness()

import cv2
from ctypes import wintypes
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from ygo_assistant.bootstrap import load_config
from ygo_assistant.capture.snapshot import save_snapshot
from ygo_assistant.ui.main_window import MainWindow
from ygo_assistant.vision.region_manager import load_profile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--layout", action="store_true")
    args = parser.parse_args()
    matches = [w for w in list_windows() if "masterduel" in "".join(w.title.lower().split())]
    if len(matches) != 1:
        raise SystemExit("Open exactly one MD window and a replay before verification")
    game = matches[0]
    api = user32()
    api.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    api.SetForegroundWindow.argtypes = [wintypes.HWND]
    api.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    api.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT]
    api.ShowWindow(game.hwnd, 9)
    original = wintypes.RECT()
    api.GetWindowRect(game.hwnd, ctypes.byref(original))
    initial_client = client_rect(game.hwnd)
    if args.layout:
        if api.GetSystemMetrics(0) < 2560:
            raise SystemExit("--layout requires a >=2560px primary monitor")
        border_w = original.right - original.left - initial_client[2] + initial_client[0]
        border_h = original.bottom - original.top - initial_client[3] + initial_client[1]
        api.SetWindowPos(game.hwnd, None, 20, 100, 1280 + border_w, 720 + border_h, 0x14)
    output = ROOT / "data/captures/md_workbench"
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    config = load_config(ROOT / "configs/app.yaml")
    window = MainWindow(config)
    if args.layout:
        window.resize(1220, 1050)
        window.move(1320, 80)
    window.show()
    api.SetForegroundWindow(game.hwnd)
    window.window_selector.setCurrentIndex(window.window_selector.findData(game.hwnd))
    report = dict(window=vars(game), capture_backend=config.capture_backend, initial_client=list(initial_client),
                  original_window=[original.left, original.top, original.right, original.bottom])
    exit_code = 1
    writer = None
    writer_size = None
    last_id = -1
    samples = []
    started = time.monotonic()
    same_profile = window.profile
    recorder = QTimer()

    def record():
        nonlocal writer, last_id, writer_size
        if window.frame is None or window.frame.source != "live_window" or window.frame.frame_id == last_id:
            return
        frame = window.frame
        size = (frame.width, frame.height)
        if writer is not None and size != writer_size:
            writer.release()
            writer = None
            samples.clear()
            report.setdefault("resolution_changes", []).append([list(writer_size), list(size)])
        if writer is None:
            writer = cv2.VideoWriter(str(output / "md_recording.mp4"), cv2.VideoWriter_fourcc(*"mp4v"),
                                     20, (frame.width, frame.height))
            assert writer.isOpened()
            writer_size = size
        writer.write(frame.image)
        samples.append((frame.frame_id, frame.timestamp_ms))
        last_id = frame.frame_id

    recorder.timeout.connect(record)
    recorder.start(50)

    def draw(name, x, y, width, height):
        window.region_selector.setCurrentIndex(window.region_selector.findData(name))
        window.draw_region()
        rect = window.preview.image_rect()
        start = QPoint(round(rect.x() + x * rect.width()), round(rect.y() + y * rect.height()))
        end = QPoint(round(rect.x() + (x + width) * rect.width()), round(rect.y() + (y + height) * rect.height()))
        QTest.mousePress(window.preview, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(window.preview, end)
        QTest.mouseRelease(window.preview, Qt.MouseButton.LeftButton, pos=end)

    def live_finished():
        nonlocal writer
        try:
            recorder.stop()
            if writer is not None:
                writer.release()
                writer = None
            assert window.pipeline.status.error is None, window.pipeline.status.error
            frame = window.frame
            assert frame is not None and frame.source == "live_window"
            assert len(samples) > 20
            assert all(a[0] < b[0] and a[1] <= b[1] for a, b in zip(samples, samples[1:]))
            draw("duel_log", .817, .130, .170, .770)
            draw("effect_text", .539, .107, .459, .096)
            assert window._dirty
            assert window.save_regions()
            assert load_profile(window.profile_path) == window.profile
            snapshot = save_snapshot(frame, window.profile, output)
            window.grab().save(str(output / "live_workbench.png"))
            report.update(live_size=[frame.width, frame.height],
                          live_received=window.pipeline.status.received, samples=samples,
                          live_elapsed_seconds=round(time.monotonic() - started, 3),
                          profile_mouse_draw_and_reload=True, snapshot=str(snapshot),
                          roi_shapes={name: list(crop.shape) for name, crop in window.profile.crops(frame).items()})
            window.open_video(output / "md_recording.mp4")
            QTimer.singleShot(900, replay_finished)
        except Exception as exc:
            report["error"] = traceback.format_exc()
            finish()

    def replay_finished():
        try:
            assert window.frame is not None and window.frame.source == "video_file"
            assert window.profile is same_profile
            assert window.frame.frame_id == 0
            assert report["roi_shapes"] == {name: list(crop.shape) for name, crop in window.profile.crops(window.frame).items()}
            window.grab().save(str(output / "replay_workbench.png"))
            report["shared_profile_and_replay_preview"] = True
            window.step(1)
            QTimer.singleShot(300, step_finished)
        except Exception as exc:
            report["error"] = traceback.format_exc()
            finish()

    def step_finished():
        nonlocal exit_code
        try:
            assert window.frame.frame_id == 1
            report["replay_step"] = True
            exit_code = 0
        except Exception as exc:
            report["error"] = traceback.format_exc()
        finish()

    def finish():
        recorder.stop()
        if writer is not None:
            writer.release()
        window._dirty = False
        window.close()
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in report.items() if k != "samples"}, ensure_ascii=False, indent=2))
        app.exit(exit_code)

    QTimer.singleShot(200, window.start_live)
    QTimer.singleShot(5200, live_finished)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
