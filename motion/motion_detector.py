"""Motion detection using frame differencing."""

from pathlib import Path
from typing import Generator

import cv2
import numpy as np


class MotionDetector:
    """Detect motion in video frames using frame differencing."""

    def __init__(
        self,
        motion_threshold: int = 5000,
        blur_ksize: int = 21,
        diff_threshold: int = 25,
    ):
        self.motion_threshold = motion_threshold
        self.blur_ksize = blur_ksize
        self.diff_threshold = diff_threshold
        self._prev_gray: np.ndarray | None = None
        self._effective_threshold: int | None = None

    def _preprocess(self, frame: np.ndarray) -> np.ndarray:
        """Convert to grayscale and blur."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if self.blur_ksize > 0:
            gray = cv2.GaussianBlur(gray, (self.blur_ksize, self.blur_ksize), 0)
        return gray

    def _count_changed_pixels(self, curr: np.ndarray) -> int:
        """Compute absolute difference with previous frame and count pixels above threshold."""
        if self._prev_gray is None:
            self._prev_gray = curr.astype(np.float32)
            return 0
        # Cap threshold by frame size so we don't require an unrealistic % of pixels (e.g. 4%)
        if self._effective_threshold is None:
            num_pixels = curr.size
            self._effective_threshold = min(
                self.motion_threshold,
                max(300, int(num_pixels * 0.004)),
            )
        curr_f = curr.astype(np.float32)
        diff = np.abs(curr_f - self._prev_gray)
        self._prev_gray = curr_f
        return int(np.sum(diff > self.diff_threshold))

    def process_frame(self, frame: np.ndarray) -> bool:
        """Process one frame; return True if motion detected."""
        gray = self._preprocess(frame)
        count = self._count_changed_pixels(gray)
        threshold = self._effective_threshold if self._effective_threshold is not None else self.motion_threshold
        return count >= threshold

    def process_frame_batch(
        self,
        frames: list[np.ndarray],
    ) -> list[bool]:
        """Process a batch of frames; returns list of motion booleans."""
        result = []
        for frame in frames:
            result.append(self.process_frame(frame))
        return result

    def motion_from_frames_dir(
        self,
        frames_dir: Path,
        pattern: str = "*.jpg",
        progress_callback=None,
    ) -> list[bool]:
        """Load frames from directory and compute motion flags."""
        paths = sorted(frames_dir.glob(pattern))
        motion_flags = []
        self._prev_gray = None
        self._effective_threshold = None
        for i, path in enumerate(paths):
            frame = cv2.imread(str(path))
            if frame is None:
                motion_flags.append(False)
                continue
            motion_flags.append(self.process_frame(frame))
            if progress_callback and (i + 1) % 100 == 0:
                progress_callback(i + 1, len(paths))
        return motion_flags

    def motion_from_frame_paths(
        self,
        paths: list[Path],
        progress_callback=None,
    ) -> list[bool]:
        """Compute motion flags from a list of frame file paths."""
        motion_flags = []
        self._prev_gray = None
        self._effective_threshold = None
        for i, path in enumerate(paths):
            frame = cv2.imread(str(path))
            if frame is None:
                motion_flags.append(False)
                continue
            motion_flags.append(self.process_frame(frame))
            if progress_callback and (i + 1) % 100 == 0:
                progress_callback(i + 1, len(paths))
        return motion_flags

    def iter_frames_from_dir(
        self,
        frames_dir: Path,
        pattern: str = "*.jpg",
        batch_size: int = 100,
    ) -> Generator[tuple[list[np.ndarray], list[float]], None, None]:
        """Yield batches of (frames, timestamps) from a frames directory.
        Timestamps are frame indices; caller should scale by 1/fps_sample.
        """
        paths = sorted(frames_dir.glob(pattern))
        for start in range(0, len(paths), batch_size):
            batch_paths = paths[start : start + batch_size]
            frames = []
            for p in batch_paths:
                f = cv2.imread(str(p))
                if f is not None:
                    frames.append(f)
            if not frames:
                continue
            indices = list(range(start, start + len(frames)))
            yield frames, [float(i) for i in indices]
