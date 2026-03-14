# Motion-based Video Trimmer

A high-performance Python tool that trims long videos by removing segments with no motion. Uses frame differencing for motion detection and FFmpeg for fast cutting/concatenation (stream copy, no re-encoding).

## Requirements

- **Python** 3.10+
- **FFmpeg** (must be installed and on your PATH)

## Installation

1. Clone or download this project.

2. Create a virtual environment (recommended):

   ```bash
   python -m venv .venv
   .venv\Scripts\activate   # Windows
   # source .venv/bin/activate   # macOS/Linux
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Ensure FFmpeg is installed:

   - **Windows**: Download from [ffmpeg.org](https://ffmpeg.org/download.html) or `winget install ffmpeg`, and add to PATH.
   - **macOS**: `brew install ffmpeg`
   - **Linux**: `sudo apt install ffmpeg` (or your distro’s package manager).

## Usage

Basic:

```bash
python main.py input.mp4
```

With options:

```bash
python main.py input.mp4 \
  --motion-threshold 5000 \
  --min-motion 1.0 \
  --min-silence 2.0 \
  --fps-sample 5 \
  -o output_trimmed.mp4 \
  --json segments.json
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `input` | (required) | Input video file |
| `-o`, `--output` | `{input_stem}_trimmed.mp4` | Output trimmed video path (or base name for clips) |
| `--motion-threshold` | 5000 | Min number of changed pixels to count as motion |
| `--min-motion` | 1.0 | Min motion segment duration (seconds) |
| `--min-silence` | 2.0 | Silence shorter than this is merged with adjacent motion (seconds) |
| `--fps-sample` | 5 | Frame rate used for motion analysis (3–5 recommended) |
| `--max-clip-duration` | 60 | Maximum duration per output clip in seconds |
| `--no-split` | — | Disable splitting; produce a single output file |
| `--json` | — | Write detected motion segments to a JSON file |
| `--no-progress` | — | Disable progress bar |
| `--debug-viz` | — | Save debug visualization (first 500 frames with motion overlay) |
| `--keep-temp` | — | Keep temporary frames and segment files |

### Example commands

Default (output: `input_trimmed.mp4`):

```bash
python main.py lecture.mp4
```

Custom output and segment log:

```bash
python main.py lecture.mp4 -o trimmed.mp4 --json segments.json
```

Stricter motion (higher threshold), longer minimum motion, longer silence gap:

```bash
python main.py input.mp4 --motion-threshold 8000 --min-motion 2.0 --min-silence 3.0 --fps-sample 4
```

Split output into 30-second clips (for easier processing):

```bash
python main.py input.mp4 --max-clip-duration 30
```

Single output file (no splitting):

```bash
python main.py input.mp4 --no-split -o trimmed.mp4
```

## Output

- **Trimmed clips**: By default, output is split into multiple clips (max 60 seconds each) saved to `{input_name}_trimmed_clips/` folder. Each clip is named `{base}_001.mp4`, `{base}_002.mp4`, etc. For example, a 1m30s trimmed video becomes two clips: one 60s clip and one 30s clip.
- **Single file mode**: Use `--no-split` to get a single concatenated output file instead of multiple clips.
- **Segments JSON** (if `--json` is set): Array of `{"start": <sec>, "end": <sec>}` for each kept segment.

## How it works

1. **Preprocessing**: FFmpeg extracts frames at a reduced rate (e.g. 5 fps) for analysis.
2. **Motion detection**: Frame differencing (grayscale, blur, absolute difference, threshold); if changed pixels ≥ `motion_threshold`, the sample is marked as motion.
3. **Segment building**: Consecutive motion samples form segments; short silence (≤ `min_silence`) is merged; segments shorter than `min_motion` are dropped.
4. **Timestamp mapping**: Sample frame indices are converted to seconds using `fps_sample`.
5. **Cutting**: Each segment is cut with `ffmpeg -ss ... -to ... -c copy`.
6. **Concatenation**: Segments are concatenated with the FFmpeg concat demuxer (`-c copy`).
7. **Splitting** (default): The concatenated video is split into multiple clips, each under `max_clip_duration` seconds (default 60s). This makes post-processing easier.

## Project structure

```
motion/
  __init__.py
  motion_detector.py   # Frame differencing motion detection
  segment_builder.py   # Motion → time segments, min motion/silence filters
  video_trimmer.py     # FFmpeg: extract frames, cut, concat
  utils.py             # FPS, duration, FFmpeg checks
main.py                # CLI entry point
requirements.txt
README.md
```

## Performance tips

- Use `--fps-sample 3` or `4` for very long videos to reduce frames and I/O.
- Increase `--motion-threshold` if you get too many false motion regions.
- Temp files are stored in the system temp dir under `motion_trim/`; ensure enough disk space for extracted frames.

