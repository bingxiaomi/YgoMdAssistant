"""Read-only capture probe, optionally records real screen frames for replay tests."""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ygo_assistant.capture.windows import enable_dpi_awareness, list_windows


def main():
    enable_dpi_awareness()
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--title", default="master duel")
    parser.add_argument("--seconds", type=float, default=3)
    parser.add_argument("--fps", type=int, default=15)
    parser.add_argument("--backend", choices=("wgc", "dxcam"), default="wgc")
    parser.add_argument("--output", type=Path, default=ROOT / "data/captures/verification")
    args = parser.parse_args()
    windows = list_windows()
    if args.list:
        print(json.dumps([vars(window) for window in windows], ensure_ascii=False, indent=2))
        return 0
    matches = [window for window in windows
               if "".join(args.title.lower().split()) in "".join(window.title.lower().split())]
    if len(matches) != 1:
        raise SystemExit(f"Expected one matching window, found {len(matches)}; use --list / --title")
    import cv2
    import numpy as np
    from ygo_assistant.capture.factory import create_live_capture
    from ygo_assistant.capture.snapshot import save_snapshot
    from ygo_assistant.capture.video_capture import VideoCapture
    from ygo_assistant.vision.region_manager import load_profile

    args.output.mkdir(parents=True, exist_ok=True)
    profile = load_profile(ROOT / "configs/regions.yaml")
    source = create_live_capture(matches[0].hwnd, backend=args.backend, fps=args.fps)
    writer = None
    writer_size = None
    recordings = []
    frames = []
    last = None
    started = time.monotonic()
    try:
        while time.monotonic() - started < args.seconds:
            before = time.monotonic()
            frame = source.read()
            if frame is not None:
                size = (frame.width, frame.height)
                if writer is not None and size != writer_size:
                    writer.release()
                    writer = None
                if writer is None:
                    filename = "md_probe.mp4" if not recordings else f"md_probe_{len(recordings):02d}.mp4"
                    recordings.append(filename)
                    writer = cv2.VideoWriter(str(args.output / filename), cv2.VideoWriter_fourcc(*"mp4v"),
                                             args.fps, (frame.width, frame.height))
                    writer_size = size
                    if not writer.isOpened():
                        raise RuntimeError("Unable to open MP4 writer")
                writer.write(frame.image)
                frames.append(dict(frame_id=frame.frame_id, timestamp_ms=frame.timestamp_ms,
                                   capture_ms=round((time.monotonic() - before) * 1000, 2)))
                last = frame
            time.sleep(max(0, 1 / args.fps - (time.monotonic() - before)))
    finally:
        source.close()
        if writer is not None:
            writer.release()
    if last is None:
        raise SystemExit("No real frames received")
    snapshot = save_snapshot(last, profile, args.output)
    video = VideoCapture(args.output / recordings[-1])
    try:
        replay = video.read()
        crops = profile.crops(replay)
    finally:
        video.close()
    report = dict(window=vars(matches[0]), backend=args.backend, width=last.width, height=last.height,
                  received=len(frames), elapsed_seconds=round(time.monotonic() - started, 3),
                  snapshot=str(snapshot), recordings=recordings, pixel_std=float(np.std(last.image)),
                  shared_roi_shapes={name: list(image.shape) for name, image in crops.items()}, frames=frames)
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "frames"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
