"""Capture one HWND's rendered surface, independent of desktop occlusion.

No resampling: strip only the native title bar/border using physical geometry.
Keep callbacks short, hold one owned BGR frame, and never synthesize repeats.
"""
import threading
import time

import numpy as np

from .base import Frame
from .windows import WindowGeometry, WindowNotReady, user32, window_geometry


class GeometryPending(ValueError):
    """Resize and capture frame have not converged yet; wait for the next frame."""


def crop_client(image: np.ndarray, geometry: WindowGeometry) -> np.ndarray:
    left, top, right, bottom = geometry.client
    width, height = right - left, bottom - top
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] not in (3, 4):
        raise ValueError("WGC frame must be uint8 BGR/BGRA")
    if image.shape[:2] == (height, width):
        return np.ascontiguousarray(image[:, :, :3]).copy()
    for bounds in (geometry.extended, geometry.outer):
        x, y, end_x, end_y = bounds
        if image.shape[:2] != (end_y - y, end_x - x):
            continue
        x0, y0 = left - x, top - y
        if 0 <= x0 and 0 <= y0 and x0 + width <= image.shape[1] and y0 + height <= image.shape[0]:
            return np.ascontiguousarray(image[y0:y0 + height, x0:x0 + width, :3]).copy()
    raise GeometryPending("窗口尺寸变化中，等待与客户区尺寸一致的新帧")


class WGCCapture:
    source = "live_window"
    ended = False

    def __init__(self, hwnd: int, fps: int = 30):
        from windows_capture import WindowsCapture

        self.hwnd = hwnd
        self._api = user32()
        if not self._api.IsWindow(hwnd):
            raise RuntimeError("选中的窗口已关闭，请刷新并重新选择")
        self._lock = threading.Lock()
        self._latest = None
        self._error = None
        self._closed = False
        self._closing = False
        self._index = 0
        self._origin_pts = None
        self._last_copy = -float("inf")
        self._period = 1 / fps
        self._last_frame_at = None
        self._wait_hint = "WGC 已连接，等待窗口原生画面"
        self._capture = WindowsCapture(window_hwnd=hwnd, cursor_capture=False)

        @self._capture.event
        def on_frame_arrived(frame, control):
            if self._closing:
                control.stop()
                return
            try:
                if self._api.IsIconic(self.hwnd):
                    # Minimized Unity windows may emit a cached last surface.
                    # Do not attach new timestamps to stale training pixels.
                    with self._lock:
                        self._latest = None
                    return
                now = time.monotonic()
                if now - self._last_copy < self._period:
                    return
                image = crop_client(frame.frame_buffer, window_geometry(self.hwnd))
                pts = int(frame.timespan)
                if self._origin_pts is None:
                    self._origin_pts = pts
                result = Frame(self._index, max(0, (pts - self._origin_pts) // 10_000),
                               image, self.source, image.shape[1], image.shape[0],
                               capture_backend="wgc", source_timestamp_100ns=pts)
                with self._lock:
                    self._latest = result
                    self._last_frame_at = now
                self._index += 1
                self._last_copy = now
            except (GeometryPending, WindowNotReady) as exc:
                self._wait_hint = str(exc)
            except Exception as exc:
                with self._lock:
                    self._error = str(exc)
                control.stop()

        @self._capture.event
        def on_closed():
            self._closed = True

        self._control = self._capture.start_free_threaded()

    @property
    def suspended(self) -> bool:
        return bool(self._api.IsIconic(self.hwnd))

    @property
    def status_message(self) -> str:
        if self._api.IsIconic(self.hwnd):
            return "窗口已最小化，等待还原；暂停接收训练帧"
        if self._last_frame_at is None:
            return self._wait_hint
        age = time.monotonic() - self._last_frame_at
        if age > 1:
            return f"等待窗口新帧 · {age:.1f} 秒未更新"
        return "WGC 原生窗口采集中 · 可后台 / 被遮挡"

    def read(self) -> Frame | None:
        if not self._api.IsWindow(self.hwnd):
            raise RuntimeError("采集窗口已关闭，请重新选择窗口")
        with self._lock:
            if self._error:
                raise RuntimeError(self._error)
            result, self._latest = self._latest, None
        if self._closed:
            raise RuntimeError("WGC 窗口捕捉会话已关闭，请重新启动采集")
        if self._api.IsIconic(self.hwnd):
            return None
        if self._control.is_finished():
            # Propagate native failures without silently switching to desktop pixels.
            self._control.wait()
            raise RuntimeError("WGC 采集会话已结束，请重新启动采集")
        return result

    def close(self) -> None:
        self._closing = True
        control, self._control = self._control, None
        if control is not None:
            if control.is_finished():
                control.wait()
            else:
                control.stop()
        with self._lock:
            self._latest = None
