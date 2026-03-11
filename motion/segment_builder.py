"""Build motion segments from motion flags and filter by duration."""

from dataclasses import dataclass


@dataclass
class Segment:
    """A time segment (start_sec, end_sec)."""

    start_sec: float
    end_sec: float

    def to_dict(self) -> dict:
        return {"start": self.start_sec, "end": self.end_sec}


class SegmentBuilder:
    """Convert motion flags to segments with min motion/silence duration filters."""

    def __init__(
        self,
        fps_sample: float,
        min_motion_duration: float = 1.0,
        min_silence_duration: float = 2.0,
    ):
        self.fps_sample = fps_sample
        self.min_motion_duration = min_motion_duration
        self.min_silence_duration = min_silence_duration
        self._frame_duration = 1.0 / fps_sample if fps_sample > 0 else 0.0

    def frame_index_to_sec(self, frame_index: int) -> float:
        """Convert sample frame index to timestamp in seconds."""
        return frame_index * self._frame_duration

    def _raw_runs(self, motion_flags: list[bool]) -> list[tuple[int, int, bool]]:
        """Get runs of motion (True) and silence (False): (start_idx, end_idx, is_motion)."""
        if not motion_flags:
            return []
        runs = []
        current = motion_flags[0]
        start = 0
        for i in range(1, len(motion_flags)):
            if motion_flags[i] != current:
                runs.append((start, i, current))
                start = i
                current = motion_flags[i]
        runs.append((start, len(motion_flags), current))
        return runs

    def build_segments(self, motion_flags: list[bool]) -> list[Segment]:
        """Build segments from motion flags, applying min motion and min silence duration."""
        runs = self._raw_runs(motion_flags)
        raw_motion = [(s, e) for s, e, m in runs if m]
        if not raw_motion:
            return []

        min_motion_frames = max(
            1,
            int(round(self.min_motion_duration * self.fps_sample)),
        )
        min_silence_frames = max(
            1,
            int(round(self.min_silence_duration * self.fps_sample)),
        )

        merged: list[tuple[int, int]] = []
        i = 0
        while i < len(runs):
            start_idx, end_idx, is_motion = runs[i]
            if not is_motion:
                i += 1
                continue
            seg_start = start_idx
            seg_end = end_idx
            j = i + 1
            while j < len(runs):
                ns, ne, nm = runs[j]
                if nm:
                    seg_end = ne
                    j += 1
                    continue
                silence_len = ne - ns
                if silence_len <= min_silence_frames and j + 1 < len(runs):
                    nn_s, nn_e, nn_m = runs[j + 1]
                    if nn_m:
                        seg_end = nn_e
                        j += 2
                        continue
                j += 1
                break
            merged.append((seg_start, seg_end))
            i = j

        segments = []
        for start_idx, end_idx in merged:
            duration_frames = end_idx - start_idx
            if duration_frames < min_motion_frames:
                continue
            start_sec = self.frame_index_to_sec(start_idx)
            end_sec = self.frame_index_to_sec(end_idx)
            segments.append(Segment(start_sec=start_sec, end_sec=end_sec))

        return segments
