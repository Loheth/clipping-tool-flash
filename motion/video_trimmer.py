"""Video trimming: extract frames, cut segments, concatenate with FFmpeg."""

import json
import subprocess
from pathlib import Path

from .segment_builder import Segment
from .utils import ensure_dir, get_temp_dir


class VideoTrimmer:
    """Orchestrate FFmpeg for frame extraction, cutting, and concatenation."""

    def __init__(self, input_path: str, temp_dir: Path | None = None):
        self.input_path = Path(input_path).resolve()
        self.temp_dir = temp_dir or (get_temp_dir() / self.input_path.stem)
        ensure_dir(self.temp_dir)

    def extract_frames(self, fps_sample: float = 5) -> Path:
        """Extract frames at given FPS to temp dir. Returns path to frames directory."""
        frames_dir = self.temp_dir / "frames"
        ensure_dir(frames_dir)
        out_pattern = str(frames_dir / "frame_%06d.jpg")
        cmd = [
            "ffmpeg",
            "-y",
            "-i", str(self.input_path),
            "-vf", f"fps={fps_sample}",
            "-q:v", "2",
            out_pattern,
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return frames_dir

    def cut_segment(
        self,
        start_sec: float,
        end_sec: float,
        output_path: Path,
        use_fast_seek: bool = True,
    ) -> Path:
        """Cut one segment using stream copy. use_fast_seek=True puts -ss before -i."""
        duration_sec = end_sec - start_sec
        cmd = ["ffmpeg", "-y"]
        if use_fast_seek:
            cmd.extend(["-ss", str(start_sec)])
        cmd.extend(["-i", str(self.input_path)])
        if not use_fast_seek:
            cmd.extend(["-ss", str(start_sec)])
        # With -ss before -i, -to is interpreted as duration; use -t for explicit duration.
        cmd.extend(["-t", str(duration_sec), "-c", "copy", str(output_path)])
        subprocess.run(cmd, check=True, capture_output=True)
        return output_path

    def cut_segments(
        self,
        segments: list[Segment],
        progress_callback=None,
    ) -> list[Path]:
        """Cut all segments; returns list of segment file paths."""
        segments_dir = self.temp_dir / "segments"
        ensure_dir(segments_dir)
        paths = []
        for i, seg in enumerate(segments):
            out = segments_dir / f"segment_{i:04d}.mp4"
            self.cut_segment(seg.start_sec, seg.end_sec, out)
            paths.append(out)
            if progress_callback:
                progress_callback(i + 1, len(segments))
        return paths

    def concat_segments(self, segment_paths: list[Path], output_path: Path) -> Path:
        """Concatenate segment files using concat demuxer (stream copy)."""
        list_file = self.temp_dir / "concat_list.txt"
        with open(list_file, "w", encoding="utf-8") as f:
            for p in segment_paths:
                line = f"file '{p.resolve()}'\n"
                f.write(line)
        cmd = [
            "ffmpeg",
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_file),
            "-c", "copy",
            str(output_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return output_path

    def cleanup(self) -> None:
        """Remove temp directory and contents."""
        import shutil
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)


def save_segments_json(segments: list[Segment], path: Path) -> None:
    """Save segment list to JSON file."""
    data = [s.to_dict() for s in segments]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
