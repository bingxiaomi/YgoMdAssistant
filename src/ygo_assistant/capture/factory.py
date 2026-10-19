def create_live_capture(hwnd: int, *, backend: str = "wgc", fps: int = 30):
    if backend == "wgc":
        from .wgc_capture import WGCCapture
        return WGCCapture(hwnd, fps=fps)
    if backend == "dxcam":
        from .dxcam_capture import DXcamCapture
        return DXcamCapture(hwnd)
    raise ValueError(f"Unsupported capture backend: {backend}")
