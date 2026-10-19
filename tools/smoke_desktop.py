"""Opt-in native desktop probe: a generated color window, DXGI, then replay UI.

Does not interact with the game. Saves reports/screenshots under data/captures.
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.pop("QT_QPA_PLATFORM", None)

from ygo_assistant.capture.windows import enable_dpi_awareness
enable_dpi_awareness()

import cv2
import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from ygo_assistant.bootstrap import AppConfig
from ygo_assistant.capture.factory import create_live_capture
from ygo_assistant.capture.frame_pipeline import FramePipeline
from ygo_assistant.capture.snapshot import save_snapshot
from ygo_assistant.ui.main_window import MainWindow
from ygo_assistant.vision.region_manager import default_profile


class Pattern(QWidget):
    def paintEvent(self, _):
        painter = QPainter(self)
        painter.fillRect(0, 0, self.width() // 2, self.height(), QColor("#e03020"))
        painter.fillRect(self.width() // 2, 0, self.width(), self.height(), QColor("#2040e0"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("wgc", "dxcam"), default="wgc")
    args = parser.parse_args()
    output = ROOT / "data/captures" / ("desktop_smoke_wgc" if args.backend == "wgc" else "desktop_smoke")
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    fixture = Pattern()
    fixture.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    fixture.setWindowTitle("YGO generated capture fixture")
    fixture.resize(640, 360)
    fixture.show()
    fixture.raise_()
    fixture_hwnd = int(fixture.winId())
    pipeline = FramePipeline(lambda: create_live_capture(fixture_hwnd, backend=args.backend), live=True)
    report = {"fixture": "generated red/blue window; not Master Duel", "backend": args.backend}
    workspace = None
    second_pipeline = None
    exit_code = 1

    def capture_finished():
        nonlocal workspace, exit_code
        try:
            frame = pipeline.frames.latest()
            if pipeline.status.error:
                raise RuntimeError(pipeline.status.error)
            if frame is None:
                raise RuntimeError("No native desktop frame received")
            assert frame.width == 640 and frame.height == 360
            # Check BGR channel order and client rectangle alignment, away from borders.
            red = frame.image[180, 160]
            blue = frame.image[180, 480]
            assert red[2] > red[0] + 40, red
            assert blue[0] > blue[2] + 40, blue
            report.update(width=frame.width, height=frame.height, received=pipeline.status.received,
                          capture_ms=pipeline.status.capture_ms, red_bgr=red.tolist(), blue_bgr=blue.tolist())
            save_snapshot(frame, default_profile(), output)
            pipeline.request_stop()
            assert pipeline.join()
            fixture.hide()
            path = output / "fixture.avi"
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (640, 360))
            assert writer.isOpened()
            for _ in range(20):
                writer.write(frame.image)
            writer.release()
            workspace = MainWindow(AppConfig())
            workspace.show()
            workspace.open_video(path)
            QTimer.singleShot(1200, finish_workspace)
        except Exception as exc:
            report["error"] = str(exc)
            finish()

    def finish_workspace():
        nonlocal second_pipeline
        try:
            assert workspace.isVisible()
            assert workspace.frame is not None
            assert workspace.frame.source == "video_file"
            workspace.grab().save(str(output / "workbench.png"))
            report["native_window_and_replay_preview"] = True
            # Reopen the same output on a fresh worker thread after releasing it.
            workspace.hide()
            fixture.show()
            fixture.raise_()
            second_pipeline = FramePipeline(lambda: create_live_capture(fixture_hwnd, backend=args.backend), live=True)
            second_pipeline.start()
            QTimer.singleShot(1000, finish_exclusion)
            return
        except Exception as exc:
            report["error"] = str(exc)
        finish()

    def finish_exclusion():
        nonlocal exit_code
        try:
            frame = second_pipeline.frames.latest()
            report["second_status"] = vars(second_pipeline.status)
            assert second_pipeline.status.error is None, second_pipeline.status.error
            assert frame is not None, "No frame after source restart"
            red, blue = frame.image[180, 160], frame.image[180, 480]
            report["second_red_bgr"] = red.tolist()
            report["second_blue_bgr"] = blue.tolist()
            save_snapshot(frame, default_profile(), output)
            assert int(red[2]) > int(red[0]) + 40, f"Unexpected red pixel: {red}"
            assert int(blue[0]) > int(blue[2]) + 40, f"Unexpected blue pixel: {blue}"
            report["reopen_capture_verified"] = True
            exit_code = 0
        except Exception as exc:
            report["error"] = str(exc)
        finish()

    def finish():
        pipeline.request_stop()
        pipeline.join()
        if second_pipeline:
            second_pipeline.request_stop()
            second_pipeline.join()
        if workspace:
            workspace.close()
        fixture.close()
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        app.exit(exit_code)

    QTimer.singleShot(500, pipeline.start)
    QTimer.singleShot(2500, capture_finished)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
