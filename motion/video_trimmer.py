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

    def split_by_duration(
        self,
        input_path: Path,
        output_dir: Path,
        max_duration_sec: float = 60.0,
        output_basename: str | None = None,
        progress_callback=None,
    ) -> list[Path]:
        """Split a video into multiple clips, each under max_duration_sec.
        
        Args:
            input_path: Path to the video file to split.
            output_dir: Directory to save clips.
            max_duration_sec: Maximum duration per clip.
            output_basename: Base name for output files (without extension).
                           If None, uses input_path stem.
            progress_callback: Optional callback(current, total).
        
        Returns list of output clip paths.
        """
        from .utils import get_video_duration
        
        basename = output_basename or input_path.stem
        total_duration = get_video_duration(str(input_path))
        if total_duration <= max_duration_sec:
            # Video is already under max duration, just copy it
            clip_path = output_dir / f"{basename}_001.mp4"
            cmd = ["ffmpeg", "-y", "-i", str(input_path), "-c", "copy", str(clip_path)]
            subprocess.run(cmd, check=True, capture_output=True)
            if progress_callback:
                progress_callback(1, 1)
            return [clip_path]
        
        # Calculate number of clips needed
        import math
        num_clips = math.ceil(total_duration / max_duration_sec)
        
        clip_paths = []
        for i in range(num_clips):
            start_sec = i * max_duration_sec
            # For the last clip, use remaining duration
            if i == num_clips - 1:
                duration_sec = total_duration - start_sec
            else:
                duration_sec = max_duration_sec
            
            clip_path = output_dir / f"{basename}_{i+1:03d}.mp4"
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(start_sec),
                "-i", str(input_path),
                "-t", str(duration_sec),
                "-c", "copy",
                str(clip_path),
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            clip_paths.append(clip_path)
            
            if progress_callback:
                progress_callback(i + 1, num_clips)
        
        return clip_paths

    def split_segments_by_duration(
        self,
        segments: list[Segment],
        output_dir: Path,
        max_duration_sec: float = 60.0,
        output_basename: str = "output",
        progress_callback=None,
    ) -> list[Path]:
        """Split motion segments into clips, never crossing segment boundaries.
        
        Each motion segment is split independently into clips of max_duration_sec.
        The last clip of each segment can be shorter than max_duration_sec.
        
        Args:
            segments: List of motion segments to process.
            output_dir: Directory to save clips.
            max_duration_sec: Maximum duration per clip.
            output_basename: Base name for output files (without extension).
            progress_callback: Optional callback(current, total).
        
        Returns list of output clip paths.
        """
        import math
        
        # First, calculate total number of clips we'll create
        total_clips = 0
        for seg in segments:
            seg_duration = seg.end_sec - seg.start_sec
            total_clips += max(1, math.ceil(seg_duration / max_duration_sec))
        
        clip_paths = []
        clip_index = 1
        clips_done = 0
        
        for seg in segments:
            seg_duration = seg.end_sec - seg.start_sec
            num_clips_in_segment = max(1, math.ceil(seg_duration / max_duration_sec))
            
            for i in range(num_clips_in_segment):
                # Calculate start time within the segment
                clip_start_offset = i * max_duration_sec
                clip_start_sec = seg.start_sec + clip_start_offset
                
                # For the last clip in this segment, use remaining duration
                if i == num_clips_in_segment - 1:
                    clip_duration = seg_duration - clip_start_offset
                else:
                    clip_duration = max_duration_sec
                
                clip_path = output_dir / f"{output_basename}_{clip_index:03d}.mp4"
                cmd = [
                    "ffmpeg", "-y",
                    "-ss", str(clip_start_sec),
                    "-i", str(self.input_path),
                    "-t", str(clip_duration),
                    "-c", "copy",
                    str(clip_path),
                ]
                subprocess.run(cmd, check=True, capture_output=True)
                clip_paths.append(clip_path)
                clip_index += 1
                clips_done += 1
                
                if progress_callback:
                    progress_callback(clips_done, total_clips)
        
        return clip_paths

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
