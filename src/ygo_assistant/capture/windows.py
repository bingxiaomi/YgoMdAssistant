"""Read-only Win32 window discovery and physical client-area coordinates."""
import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    pid: int


@dataclass(frozen=True)
class WindowGeometry:
    client: tuple[int, int, int, int]
    extended: tuple[int, int, int, int]
    outer: tuple[int, int, int, int]


class WindowNotReady(RuntimeError):
    """A live window is minimized or has a transient empty client area."""


def window_geometry(hwnd: int) -> WindowGeometry:
    """All rectangles in physical screen pixels; call on non-minimized windows."""
    api = user32()
    try:
        client = client_rect(hwnd)
    except RuntimeError as exc:
        if api.IsWindow(hwnd):
            raise WindowNotReady(str(exc)) from exc
        raise
    api.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    outer, extended = wintypes.RECT(), wintypes.RECT()
    if not api.GetWindowRect(hwnd, ctypes.byref(outer)):
        raise ctypes.WinError(ctypes.get_last_error())
    dwm = ctypes.WinDLL("dwmapi")
    dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    result = dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(extended), ctypes.sizeof(extended))
    def coords(rect):
        return rect.left, rect.top, rect.right, rect.bottom
    return WindowGeometry(client, coords(extended) if result == 0 else coords(outer), coords(outer))


def user32():
    if os.name != "nt":
        raise RuntimeError("实时窗口采集仅支持 Windows")
    api = ctypes.WinDLL("user32", use_last_error=True)
    api.GetForegroundWindow.restype = wintypes.HWND
    api.IsWindow.argtypes = [wintypes.HWND]
    api.IsWindowVisible.argtypes = [wintypes.HWND]
    api.IsIconic.argtypes = [wintypes.HWND]
    api.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    api.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    api.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    api.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    api.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    api.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    api.MonitorFromWindow.restype = wintypes.HMONITOR
    return api


def enable_dpi_awareness() -> None:
    if os.name == "nt":
        api = user32()
        try:
            api.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            api.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except AttributeError:
            api.SetProcessDPIAware()


def list_windows() -> list[WindowInfo]:
    api = user32()
    windows = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def visit(hwnd, _):
        length = api.GetWindowTextLengthW(hwnd)
        if length and api.IsWindowVisible(hwnd):
            title = ctypes.create_unicode_buffer(length + 1)
            api.GetWindowTextW(hwnd, title, length + 1)
            pid = wintypes.DWORD()
            api.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value != os.getpid():
                windows.append(WindowInfo(int(hwnd), title.value, pid.value))
        return True

    api.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    if not api.EnumWindows(visit, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return sorted(windows, key=lambda w: ("masterduel" not in "".join(w.title.lower().split()), w.title.lower()))


def client_rect(hwnd: int) -> tuple[int, int, int, int]:
    api = user32()
    if not api.IsWindow(hwnd):
        raise RuntimeError("选中的窗口已关闭，请刷新并重新选择")
    if api.IsIconic(hwnd):
        raise RuntimeError("游戏窗口已最小化，请还原窗口后继续采集")
    rect, point = wintypes.RECT(), wintypes.POINT()
    if not api.GetClientRect(hwnd, ctypes.byref(rect)) or not api.ClientToScreen(hwnd, ctypes.byref(point)):
        raise ctypes.WinError(ctypes.get_last_error())
    if rect.right <= 0 or rect.bottom <= 0:
        raise RuntimeError("窗口客户区为空")
    return point.x, point.y, point.x + rect.right, point.y + rect.bottom
