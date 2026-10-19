"""Record one manually selected replay: CFR review MP4 + untouched PNG evidence.

PNG/ROI samples only originate from new WGC frames. Review video duplication is
explicit in video_frames.jsonl and is never exported as new source evidence.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import cv2
import numpy as np

from ygo_assistant.capture.factory import create_live_capture
from ygo_assistant.capture.snapshot import save_snapshot
from ygo_assistant.capture.windows import enable_dpi_awareness, list_windows
from ygo_assistant.vision.region_manager import load_profile


def finish_mask(image):
    height, width = image.shape[:2]
    region = image[int(height * .38):int(height * .63), int(width * .07):int(width * .94)]
    return ((region.min(axis=2) > 210) & (np.ptp(region, axis=2) < 50)).astype(np.uint8) * 255


def png(path, image):
    success, data = cv2.imencode(".png", image)
    if not success:
        raise RuntimeError("PNG encoding failed")
    path.write_bytes(data.tobytes())


def main():
    enable_dpi_awareness()
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--end-reference", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=900)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    roi_directory = args.output / "roi"
    roi_directory.mkdir(exist_ok=True)
    profile = load_profile(ROOT / "configs/regions.yaml")
    (args.output / "regions.json").write_text(profile.model_dump_json(indent=2), encoding="utf-8")
    reference_image = cv2.imdecode(np.frombuffer(args.end_reference.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    reference = finish_mask(reference_image)
    game = next(window for window in list_windows() if "masterduel" in "".join(window.title.lower().split()))
    source = create_live_capture(game.hwnd, backend="wgc", fps=30)
    started = time.monotonic()
    last = None
    writer = None
    writer_size = None
    video_index = 0
    previous_video_source = None
    png_count = roi_count = source_count = duplicate_count = 0
    next_tick = started
    next_png = next_roi = next_status = next_finish_check = 0
    end_hits = 0
    reason = "time_limit"
    source_rows = args.output / "source_frames.jsonl"
    video_rows = args.output / "video_frames.jsonl"
    received_at = None
    try:
        with source_rows.open("w", encoding="utf-8") as raw, video_rows.open("w", encoding="utf-8") as review:
            while time.monotonic() - started < args.seconds:
                now = time.monotonic()
                elapsed = now - started
                if (args.output / "STOP").exists():
                    reason = "manual_stop"
                    break
                frame = source.read()
                if frame is not None:
                    last = frame
                    received_at = now
                    source_count += 1
                    row = dict(frame_id=frame.frame_id, timestamp_ms=frame.timestamp_ms,
                               source_timestamp_100ns=frame.source_timestamp_100ns,
                               elapsed_seconds=round(elapsed, 4), width=frame.width, height=frame.height)
                    if elapsed >= next_roi:
                        paths = {}
                        for name, crop in profile.crops(frame).items():
                            path = roi_directory / f"{roi_count:06d}_{name}.png"
                            png(path, crop)
                            paths[name] = str(path.relative_to(args.output))
                        row["roi_png"] = paths
                        roi_count += 1
                        next_roi = elapsed + .5
                    if elapsed >= next_png:
                        row["snapshot"] = str(save_snapshot(frame, profile, args.output / "snapshots").relative_to(args.output))
                        png_count += 1
                        next_png = elapsed + 5
                    raw.write(json.dumps(row, ensure_ascii=False) + "\n")
                    if elapsed >= next_finish_check:
                        mask = finish_mask(frame.image)
                        score = float(cv2.matchTemplate(mask, reference, cv2.TM_CCOEFF_NORMED)[0, 0]) if mask.shape == reference.shape else 0
                        end_hits = end_hits + 1 if score > .88 and elapsed > 30 else 0
                        next_finish_check = elapsed + .5
                        if end_hits >= 3:
                            save_snapshot(frame, profile, args.output / "ending")
                            reason = "finish_banner_detected"
                            break
                if last is not None and now >= next_tick:
                    size = (last.width, last.height)
                    if writer is None:
                        writer = cv2.VideoWriter(str(args.output / "replay.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 15, size)
                        if not writer.isOpened():
                            raise RuntimeError("Unable to create review MP4")
                        writer_size = size
                        next_tick = now
                    if size != writer_size:
                        reason = "resolution_changed"
                        break
                    # Keep wall-clock playback duration; mark explicit CFR duplicates.
                    while next_tick <= now:
                        repeated = last.frame_id == previous_video_source
                        writer.write(last.image)
                        review.write(json.dumps(dict(video_index=video_index, source_frame_id=last.frame_id,
                                                     timestamp_ms=last.timestamp_ms, repeated=repeated)) + "\n")
                        duplicate_count += int(repeated)
                        previous_video_source = last.frame_id
                        video_index += 1
                        next_tick += 1 / 15
                if elapsed >= next_status and last is not None:
                    png(args.output / "latest.png", last.image)
                    state = dict(elapsed_seconds=round(elapsed, 2), source_frames=source_count,
                                 video_frames=video_index, snapshots=png_count, roi_pairs=roi_count,
                                 size=[last.width, last.height], frame_age_seconds=round(now - received_at, 3),
                                 status=source.status_message)
                    (args.output / "progress.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
                    raw.flush()
                    review.flush()
                    next_status = elapsed + 2
                time.sleep(.008)
    finally:
        source.close()
        if writer is not None:
            writer.release()
    report = dict(schema_version="1.0", window=vars(game), backend="wgc", stop_reason=reason,
                  elapsed_seconds=round(time.monotonic() - started, 3), source_frames=source_count,
                  video_frames=video_index, video_fps=15, cfr_repeated_frames=duplicate_count,
                  native_size=writer_size, full_png_snapshots=png_count, roi_png_pairs=roi_count,
                  raw_png_interval_seconds=5, roi_interval_seconds=.5,
                  note="Review MP4 is lossy CFR; PNG evidence is native and lossless. Requires manual dataset review.")
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
