import time

import numpy as np

from .base import Frame
from .windows import client_rect, user32


class DXcamCapture:
    """Capture the selected physical client area from its desktop output.

    Desktop Duplication captures visible pixels, including occluding windows.
    The small DXcam discovery bridge is pinned to version 0.3.0.
    """
    source = "live_window"
    ended = False

    def __init__(self, hwnd: int):
        import comtypes
        comtypes.CoInitialize()
        self._com = comtypes
        self._com_open = True
        self._camera = None
        try:
            self._initialize(hwnd)
        except Exception:
            self.close()
            raise

    def _initialize(self, hwnd):
        import dxcam

        self.hwnd = hwnd
        self._dxcam = dxcam
        self._camera = None
        self._monitor = None
        self._started = time.monotonic()
        self._index = 0
        client_rect(hwnd)

    def _select_output(self, monitor):
        self._release_camera()
        # DXcam's public output_info omits HMONITOR; isolate its version-specific
        # discovery metadata here rather than assume EnumDisplayMonitors ordering.
        factory = vars(self._dxcam).get("__factory")
        if factory is None:
            raise RuntimeError("DXcam 显示器映射接口不兼容，请安装锁定版本")
        for device_idx, outputs in enumerate(factory.outputs):
            for output_idx, output in enumerate(outputs):
                output.update_desc()
                if output.hmonitor == monitor:
                    self._camera = self._dxcam.create(
                        device_idx=device_idx, output_idx=output_idx,
                        output_color="BGR", max_buffer_len=2,
                    )
                    self._monitor = monitor
                    self._output = output
                    return
        raise RuntimeError("未找到游戏窗口所在的显示器；显示配置变化后请重启采集")

    def read(self) -> Frame | None:
        left, top, right, bottom = client_rect(self.hwnd)
        monitor = user32().MonitorFromWindow(self.hwnd, 2)
        if self._camera is None or monitor != self._monitor:
            self._select_output(monitor)
        self._output.update_desc()
        bounds = self._output.desc.DesktopCoordinates
        if left < bounds.left or top < bounds.top or right > bounds.right or bottom > bounds.bottom:
            raise RuntimeError("请将游戏客户区完整放在同一显示器内，避免跨屏或超出屏幕")
        region = (left - bounds.left, top - bounds.top, right - bounds.left, bottom - bounds.top)
        image = self._camera.grab(region=region, new_frame_only=False)
        if image is None:
            return None
        image = np.ascontiguousarray(image).copy()
        frame = Frame(self._index, round((time.monotonic() - self._started) * 1000),
                      image, self.source, image.shape[1], image.shape[0], capture_backend="dxcam")
        self._index += 1
        return frame

    def _release_camera(self) -> None:
        if self._camera is not None:
            self._camera.release()
            self._camera = None
        self._monitor = None

    def close(self) -> None:
        try:
            self._release_camera()
        finally:
            if self._com_open:
                self._com.CoUninitialize()
                self._com_open = False
