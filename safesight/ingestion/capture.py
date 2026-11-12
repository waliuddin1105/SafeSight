"""Bound native camera reads in a disposable process, including blocked USB drivers."""

import multiprocessing
from queue import Empty, Full
import time


def _capture(target, rtsp: bool, fps: float, queue) -> None:
    import cv2

    cv2.setLogLevel(0)
    capture = cv2.VideoCapture()
    try:
        if rtsp:
            capture.open(
                target, cv2.CAP_FFMPEG, [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 10000]
            )
        else:
            capture.open(target)
        while capture.isOpened():
            ok, frame = capture.read()
            if not ok:
                break
            try:
                queue.put(frame, block=False)
            except Full:
                pass
            time.sleep(1 / fps)
    finally:
        capture.release()
        try:
            queue.put(None, timeout=1)
        except Full:
            pass


class CaptureReader:
    """Keep native I/O out of the inference process and enforce a read deadline."""

    def __init__(self, target, rtsp: bool = False, fps: float = 5, timeout: float = 10):
        context = multiprocessing.get_context("spawn")
        self.queue = context.Queue(maxsize=1)
        self.timeout = timeout
        self.process = context.Process(target=_capture, args=(target, rtsp, fps, self.queue), daemon=True)
        self.process.start()

    def read(self):
        try:
            frame = self.queue.get(timeout=self.timeout)
            return frame is not None, frame
        except Empty:
            return False, None

    def release(self) -> None:
        if self.process.is_alive():
            self.process.terminate()
        self.process.join(timeout=1)
        self.queue.cancel_join_thread()
        self.queue.close()
