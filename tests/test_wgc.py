import sys
from types import SimpleNamespace

import numpy as np
import pytest

from ygo_assistant.capture import wgc_capture as wgc
from ygo_assistant.capture.windows import WindowGeometry


def test_native_client_crop_strips_title_without_resampling():
    geometry = WindowGeometry((256, 155, 2304, 1307), (255, 124, 2305, 1308), (248, 124, 2312, 1315))
    image = np.arange(1184 * 2050 * 4, dtype=np.uint8).reshape(1184, 2050, 4)
    result = wgc.crop_client(image, geometry)
    assert result.shape == (1152, 2048, 3)
    assert result.flags.c_contiguous
    assert np.array_equal(result, image[31:1183, 1:2049, :3])
    image[:] = 0
    assert np.any(result)  # The callback's borrowed native memory is never retained.


def test_client_only_frame_and_geometry_transition():
    geometry = WindowGeometry((1, 1, 9, 5), (0, 0, 10, 6), (0, 0, 10, 6))
    image = np.zeros((4, 8, 4), np.uint8)
    assert wgc.crop_client(image, geometry).shape == (4, 8, 3)
    with pytest.raises(wgc.GeometryPending):
        wgc.crop_client(np.zeros((3, 3, 4), np.uint8), geometry)


def test_wgc_new_frames_minimize_resume_and_cleanup(monkeypatch):
    state = {"minimized": False, "now": 0.0}
    api = SimpleNamespace(IsWindow=lambda _: True, IsIconic=lambda _: state["minimized"])
    geometry = WindowGeometry((1, 1, 9, 5), (0, 0, 10, 6), (0, 0, 10, 6))
    monkeypatch.setattr(wgc, "user32", lambda: api)
    monkeypatch.setattr(wgc, "window_geometry", lambda _: geometry)
    monkeypatch.setattr(wgc.time, "monotonic", lambda: state["now"])

    class Control:
        stopped = False
        def is_finished(self): return False
        def stop(self): self.stopped = True

    class Capture:
        def __init__(self, **kwargs):
            assert kwargs["window_hwnd"] == 123  # Exact HWND, no title substring fallback.
            self.control = Control()
            state["capture"] = self
        def event(self, handler):
            setattr(self, handler.__name__, handler)
            return handler
        def start_free_threaded(self): return self.control

    monkeypatch.setitem(sys.modules, "windows_capture", SimpleNamespace(WindowsCapture=Capture))
    source = wgc.WGCCapture(123)
    capture = state["capture"]
    image = np.full((6, 10, 4), 42, np.uint8)
    native = SimpleNamespace(frame_buffer=image, timespan=100_000_000)
    capture.on_frame_arrived(native, capture.control)
    first = source.read()
    assert first.width == 8 and first.height == 4
    assert first.capture_backend == "wgc" and first.timestamp_ms == 0
    assert source.read() is None  # Never relabel cached pixels as fresh frames.
    state["now"] = 1.0
    state["minimized"] = True
    capture.on_frame_arrived(native, capture.control)
    assert source.read() is None
    assert "最小化" in source.status_message
    state["minimized"] = False
    native.timespan = 110_000_000
    capture.on_frame_arrived(native, capture.control)
    resumed = source.read()
    assert resumed.timestamp_ms == 1000 and resumed.frame_id == 1
    assert resumed.source_timestamp_100ns == 110_000_000
    # Unity briefly exposes a zero-sized client area while restoring.
    def not_ready(_):
        raise wgc.WindowNotReady("窗口客户区为空")
    state["now"] = 2.0
    monkeypatch.setattr(wgc, "window_geometry", not_ready)
    capture.on_frame_arrived(native, capture.control)
    assert source.read() is None
    assert not capture.control.stopped
    state["now"] = 3.0
    native.timespan = 130_000_000
    monkeypatch.setattr(wgc, "window_geometry", lambda _: geometry)
    capture.on_frame_arrived(native, capture.control)
    assert source.read().timestamp_ms == 3000
    source.close()
    source.close()
    assert capture.control.stopped
