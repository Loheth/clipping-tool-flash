#!/usr/bin/env python3
"""
Motion-based video trimmer: remove segments with no motion from long videos.
"""

import argparse
import math
import sys
from pathlib import Path

from motion.motion_detector import MotionDetector
from motion.segment_builder import SegmentBuilder
from motion.utils import check_ffmpeg, ensure_dir, get_video_duration
from motion.video_trimmer import VideoTrimmer, save_segments_json


def parse_args():
    parser = argparse.ArgumentParser(
        description="Trim video by removing segments with no motion.",
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Input video file",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Output trimmed video path (default: input_trimmed.mp4)",
    )
    parser.add_argument(
        "--motion-threshold",
        type=int,
        default=1500,
        help="Min number of changed pixels to count as motion (default: 1500; capped by frame size)",
    )
    parser.add_argument(
        "--min-motion",
        type=float,
        default=0.5,
        dest="min_motion",
        help="Min motion segment duration in seconds (default: 0.5)",
    )
    parser.add_argument(
        "--min-silence",
        type=float,
        default=3.0,
        dest="min_silence",
        help="Silence shorter than this is merged with adjacent motion (default: 3.0)",
    )
    parser.add_argument(
        "--fps-sample",
        type=float,
        default=5,
        dest="fps_sample",
        help="Frame rate for motion analysis (default: 5)",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Write detected motion segments to this JSON file",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable progress bar",
    )
    parser.add_argument(
        "--debug-viz",
        action="store_true",
        help="Save debug visualization (motion overlay frames)",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep temporary frames and segments (for debugging)",
    )
    parser.add_argument(
        "--max-clip-duration",
        type=float,
        default=60.0,
        dest="max_clip_duration",
        help="Maximum duration for each output clip in seconds (default: 60). Output will be split into multiple clips if longer.",
    )
    parser.add_argument(
        "--no-split",
        action="store_true",
        help="Disable splitting output into multiple clips (produces single output file)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    input_path = args.input.resolve()
    if not input_path.is_file():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)
    if not check_ffmpeg():
        print("Error: ffmpeg not found. Please install ffmpeg and ensure it is on PATH.", file=sys.stderr)
        sys.exit(1)

    output_path = args.output or (input_path.parent / f"{input_path.stem}_trimmed.mp4")
    output_path = output_path.resolve()
    ensure_dir(output_path.parent)

    show_progress = not args.no_progress
    try:
        from tqdm import tqdm
    except ImportError:
        tqdm = None
        show_progress = False

    trimmer = VideoTrimmer(str(input_path))
    duration_sec = get_video_duration(str(input_path))
    print(f"Input: {input_path}")
    print(f"Duration: {duration_sec:.1f}s | Sampling at {args.fps_sample} fps for motion detection")

    # 1. Extract frames
    if show_progress and tqdm:
        print("Extracting frames for motion analysis...")
    frames_dir = trimmer.extract_frames(fps_sample=args.fps_sample)
    frame_paths = sorted(frames_dir.glob("frame_*.jpg"))
    n_frames = len(frame_paths)
    print(f"Extracted {n_frames} frames.")

    # 2. Motion detection
    detector = MotionDetector(motion_threshold=args.motion_threshold)
    if show_progress and tqdm:
        pbar = tqdm(total=n_frames, unit="frames", desc="Motion detection")
        def on_progress(current, total):
            pbar.n = current
            pbar.refresh()
        motion_flags = detector.motion_from_frame_paths(frame_paths, progress_callback=on_progress)
        pbar.close()
    else:
        motion_flags = detector.motion_from_frame_paths(frame_paths)
    motion_count = sum(1 for m in motion_flags if m)
    motion_pct = 100.0 * motion_count / n_frames if n_frames else 0
    print(f"Motion detected in {motion_count} / {n_frames} sample frames ({motion_pct:.1f}%).")
    if n_frames and motion_pct < 15:
        print("  Tip: if this seems low, try --motion-threshold 800 or 500 for more sensitivity.")

    # 3. Build segments
    builder = SegmentBuilder(
        fps_sample=args.fps_sample,
        min_motion_duration=args.min_motion,
        min_silence_duration=args.min_silence,
    )
    segments = builder.build_segments(motion_flags)
    if not segments:
        print("No motion segments found. Output would be empty; exiting.")
        if not args.keep_temp:
            trimmer.cleanup()
        sys.exit(1)
    total_kept = sum(s.end_sec - s.start_sec for s in segments)
    print(f"Found {len(segments)} motion segments (total {total_kept:.1f}s).")

    if args.json:
        save_segments_json(segments, args.json.resolve())
        print(f"Wrote segments to {args.json}")

    # Optional debug visualization
    if args.debug_viz and frame_paths:
        try:
            import cv2
            viz_dir = trimmer.temp_dir / "debug_viz"
            viz_dir.mkdir(exist_ok=True)
            for i, (path, has_motion) in enumerate(zip(frame_paths[:500], motion_flags[:500])):
                img = cv2.imread(str(path))
                if img is not None:
                    if has_motion:
                        img[:, :, 1] = 255
                    cv2.imwrite(str(viz_dir / f"viz_{i:05d}.jpg"), img)
            print(f"Debug viz saved to {viz_dir}")
        except Exception as e:
            print(f"Debug viz failed: {e}")

    # 4. Cut segments
    if show_progress and tqdm:
        pbar_cut = tqdm(total=len(segments), unit="seg", desc="Cutting segments")
        def on_cut(i, n):
            pbar_cut.n = i
            pbar_cut.refresh()
        segment_paths = trimmer.cut_segments(segments, progress_callback=on_cut)
        pbar_cut.close()
    else:
        segment_paths = trimmer.cut_segments(segments)
    print(f"Cut {len(segment_paths)} segments.")

    # 5. Concat into intermediate file
    if args.no_split:
        # Single output file mode
        trimmer.concat_segments(segment_paths, output_path)
        print(f"Output: {output_path}")
    else:
        # Split into multiple clips mode
        intermediate_path = trimmer.temp_dir / "concatenated_temp.mp4"
        trimmer.concat_segments(segment_paths, intermediate_path)
        
        # Create output directory for clips
        output_dir = output_path.parent / f"{output_path.stem}_clips"
        ensure_dir(output_dir)
        
        # 6. Split into clips under max duration
        if show_progress and tqdm:
            total_dur = get_video_duration(str(intermediate_path))
            num_clips = max(1, math.ceil(total_dur / args.max_clip_duration))
            pbar_split = tqdm(total=num_clips, unit="clip", desc="Splitting into clips")
            def on_split(i, n):
                pbar_split.n = i
                pbar_split.refresh()
            clip_paths = trimmer.split_by_duration(
                intermediate_path,
                output_dir,
                max_duration_sec=args.max_clip_duration,
                output_basename=output_path.stem,
                progress_callback=on_split,
            )
            pbar_split.close()
        else:
            clip_paths = trimmer.split_by_duration(
                intermediate_path,
                output_dir,
                max_duration_sec=args.max_clip_duration,
                output_basename=output_path.stem,
            )
        
        print(f"\nOutput: {len(clip_paths)} clips saved to {output_dir}/")
        for i, clip_path in enumerate(clip_paths, 1):
            clip_duration = get_video_duration(str(clip_path))
            print(f"  Clip {i}: {clip_path.name} ({clip_duration:.1f}s)")

    if not args.keep_temp:
        trimmer.cleanup()
    print("Done.")


if __name__ == "__main__":
    main()
