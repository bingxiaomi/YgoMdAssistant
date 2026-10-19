import time

import cv2
import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from ygo_assistant.bootstrap import AppConfig
from ygo_assistant.ui.frame_view import FrameView, fit_rect
from ygo_assistant.ui.main_window import MainWindow
from ygo_assistant.vision.region_manager import default_profile


def test_letterbox_geometry():
    rect = fit_rect(1000, 1000, 1920, 1080)
    assert rect.x() == pytest.approx(0, abs=1e-9)
    assert rect.y() == pytest.approx(218.75)
    assert rect.width() == pytest.approx(1000)
    assert rect.height() == pytest.approx(562.5)


def test_drag_region_uses_image_coordinates(qt_app):
    view = FrameView()
    view.resize(800, 600)
    view.profile = default_profile()
    view.set_image(np.zeros((400, 800, 3), np.uint8))
    view.show()
    qt_app.processEvents()
    view.force_draw = True
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(400, 200))
    QTest.mouseMove(view, QPoint(720, 460))
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPoint(720, 460))
    region = view.profile.regions["duel_log"]
    assert region.x == pytest.approx(.5)
    assert region.y == pytest.approx(.25)
    assert region.width == pytest.approx(.4)
    assert region.height == pytest.approx(.65)
    # Mouse actions on letterbox bars must not change image geometry.
    previous = region.model_dump()
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    QTest.mouseMove(view, QPoint(100, 60))
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPoint(100, 60))
    assert view.profile.regions["duel_log"].model_dump() == previous
    view.close()


def test_ui_video_controls_and_roi_retained(qt_app, tmp_path):
    path = tmp_path / "clip.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (80, 40))
    assert writer.isOpened()
    for i in range(10):
        writer.write(np.full((40, 80, 3), i * 20, np.uint8))
    writer.release()
    window = MainWindow(AppConfig(regions_path=tmp_path / "regions.yaml"))
    window.show()
    window.open_video(path)
    profile = window.profile

    def wait_id(expected):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            qt_app.processEvents()
            if window.frame is not None and window.frame.frame_id == expected:
                return
            time.sleep(.005)
        raise AssertionError(f"UI did not display frame {expected}")

    try:
        wait_id(0)
        assert window.play_button.isEnabled()
        window.step(1)
        wait_id(1)
        assert window.save_regions()
        window.stop_capture()
        window.open_video(path)
        wait_id(0)
        assert window.profile is profile
    finally:
        window.close()
