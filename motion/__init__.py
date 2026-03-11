"""Motion-based video trimming package."""

from .motion_detector import MotionDetector
from .segment_builder import SegmentBuilder
from .video_trimmer import VideoTrimmer

__all__ = ["MotionDetector", "SegmentBuilder", "VideoTrimmer"]
