"""Validated export preferences shared by settings and queued task snapshots."""
from runtime_paths import read_settings
from media_export import AUDIO_BITRATES, IMAGE_FORMATS, VIDEO_FORMATS


def export_preferences(values=None):
    saved = read_settings() if values is None else values
    video = saved.get("video_format", "mp4")
    image = saved.get("image_format", "png")
    try:
        bitrate = int(saved.get("audio_bitrate", 192))
    except (TypeError, ValueError):
        bitrate = 192
    return {"video_format": video if video in VIDEO_FORMATS else "mp4",
            "image_format": image if image in IMAGE_FORMATS else "png",
            "audio_bitrate": bitrate if bitrate in AUDIO_BITRATES else 192}
