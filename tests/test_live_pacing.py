import threading
import time

import numpy as np

from ygo_assistant.capture.base import Frame
from ygo_assistant.capture.frame_pipeline import FramePipeline


def test_live_pacing_and_thread_owned_cleanup():
    first = threading.Event()
    records = {"reads": 0}

    class Reader:
        ended = False
        source = "live_window"

        def __init__(self):
            records["owner"] = threading.get_ident()
            self.started = time.monotonic()

        def read(self):
            assert threading.get_ident() == records["owner"]
            records["reads"] += 1
            first.set()
            return Frame(records["reads"], round((time.monotonic() - self.started) * 1000),
                         np.zeros((2, 2, 3), np.uint8), self.source, 2, 2)

        def close(self):
            records["closed_on"] = threading.get_ident()

    pipeline = FramePipeline(Reader, live=True, capture_fps=20)
    pipeline.start()
    assert first.wait(2)
    time.sleep(.21)
    pipeline.request_stop()
    assert pipeline.join()
    assert 2 <= records["reads"] <= 7
    assert records["closed_on"] == records["owner"]
