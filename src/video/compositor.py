"""
Compositor - Assembles video using FFmpeg.

Handles:
- Timeline assembly
- Transitions
- Text overlays
- Audio mixing
- Post-processing
"""

import asyncio
import os
from pathlib import Path
from typing import Any

from .platform_specs import SafeZone, get_platform_format
from .schemas import TextAnimation, TextPosition


class Compositor:
    """
    Composes final video from assets using FFmpeg.
    """

    # Text position coordinates (for 1080x1920)
    POSITION_COORDS: dict[TextPosition, tuple[str, str]] = {
        TextPosition.TOP_CENTER: ("(w-text_w)/2", "100"),
        TextPosition.CENTER: ("(w-text_w)/2", "(h-text_h)/2"),
        TextPosition.BOTTOM_CENTER: ("(w-text_w)/2", "h-text_h-150"),
        TextPosition.TOP_LEFT: ("50", "100"),
        TextPosition.TOP_RIGHT: ("w-text_w-50", "100"),
        TextPosition.BOTTOM_LEFT: ("50", "h-text_h-150"),
        TextPosition.BOTTOM_RIGHT: ("w-text_w-50", "h-text_h-150"),
    }

    def __init__(
        self,
        ffmpeg_path: str = "ffmpeg",
        ffprobe_path: str = "ffprobe",
        output_dir: str = "/tmp/creative_master/output",
        font_path: str | None = None,
    ):
        """
        Initialize compositor.

        Args:
            ffmpeg_path: Path to ffmpeg executable
            ffprobe_path: Path to ffprobe executable
            output_dir: Directory for output files
            font_path: Path to font file for text overlays
        """
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Use system font if not specified
        self.font_path = font_path or self._find_system_font()

    async def _detect_h264_encoder(self) -> tuple[str, list[str]]:
        """Detect the best available H.264 encoder and its flags.

        Returns:
            Tuple of (encoder_name, extra_flags).
        """
        # Try libx264 first (software, most flexible)
        try:
            process = await asyncio.create_subprocess_exec(
                self.ffmpeg_path, "-encoders",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()
            encoders = stdout.decode()
        except Exception:
            return ("libx264", ["-preset", "medium", "-crf", "23"])

        if "libx264" in encoders:
            return ("libx264", ["-preset", "medium", "-crf", "23"])
        if "h264_videotoolbox" in encoders:
            return ("h264_videotoolbox", ["-q:v", "65"])
        # Fallback
        return ("libx264", ["-preset", "medium", "-crf", "23"])

    def _find_system_font(self) -> str:
        """Find a suitable system font."""
        # Common font paths
        font_paths = [
            "/System/Library/Fonts/Helvetica.ttc",  # macOS
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Linux
            "C:\\Windows\\Fonts\\arial.ttf",  # Windows
        ]
        for path in font_paths:
            if os.path.exists(path):
                return path
        return "arial"  # Fallback to font name

    async def compose(
        self,
        shots: list[dict[str, Any]],
        output_path: str,
    ) -> dict[str, Any]:
        """
        Compose video from shots.

        Args:
            shots: List of shot specifications with video paths
            output_path: Path for output video

        Returns:
            Composition result
        """
        if not shots:
            return {"error": "No shots provided"}

        # Sort shots by number
        sorted_shots = sorted(shots, key=lambda s: s.get("shot_number", 0))

        # Build FFmpeg command
        try:
            result = await self._run_ffmpeg_compose(sorted_shots, output_path)

            text_overlays = sum(
                1 for s in sorted_shots if s.get("text_overlay")
            )

            return {
                "shots_assembled": len(sorted_shots),
                "order_preserved": True,
                "text_overlays_applied": text_overlays,
                "output_path": output_path,
                **result,
            }
        except Exception as e:
            return {
                "error": str(e),
                "shots_assembled": 0,
                "order_preserved": False,
            }

    async def _run_ffmpeg_compose(
        self,
        shots: list[dict[str, Any]],
        output_path: str,
    ) -> dict[str, Any]:
        """
        Run FFmpeg to compose video using the concat filter.

        Uses the concat filter (not demuxer) for correct timestamp
        handling across clips with different timestamp bases.

        This is separated to allow mocking in tests.
        """
        # Collect valid video paths
        video_paths = []
        for shot in shots:
            video_path = shot.get("video_path", "")
            if video_path and os.path.exists(video_path):
                video_paths.append(video_path)

        if not video_paths:
            return {"error": "No video files to compose"}

        # Detect best encoder
        encoder, encoder_flags = await self._detect_h264_encoder()

        n = len(video_paths)

        # Build concat filter command — video only (audio mixed separately)
        inputs: list[str] = []
        for path in video_paths:
            inputs.extend(["-i", path])

        filter_inputs = "".join(f"[{i}:v]" for i in range(n))
        filter_str = f"{filter_inputs}concat=n={n}:v=1:a=0[outv]"

        cmd = [
            self.ffmpeg_path,
            "-y",
            *inputs,
            "-filter_complex", filter_str,
            "-map", "[outv]",
            "-c:v", encoder,
            *encoder_flags,
            output_path,
        ]

        await self._run_command(cmd)
        return {"success": True}

    async def _run_ffmpeg(self, *args: str) -> bool:
        """
        Run FFmpeg command.

        Returns True if successful.
        """
        cmd = [self.ffmpeg_path, "-y", *args]
        return await self._run_command(cmd)

    async def _run_command(self, cmd: list[str]) -> bool:
        """Run a shell command asynchronously."""
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError(f"Command failed: {stderr.decode()}")

        return True

    async def trim_clip(
        self,
        input_path: str,
        output_path: str,
        duration: float,
        target_width: int | None = None,
        target_height: int | None = None,
    ) -> dict[str, Any]:
        """Trim a video clip to an exact duration, optionally scaling.

        Re-encodes to get frame-accurate cuts (stream copy only
        cuts at keyframes, producing inaccurate durations).

        When target_width/height are provided, scales the clip to
        the target resolution so all clips are consistent for concat.

        Args:
            input_path: Input video path.
            output_path: Output video path.
            duration: Target duration in seconds.
            target_width: Target width (optional, for resolution normalization).
            target_height: Target height (optional, for resolution normalization).

        Returns:
            Result dict with success status.
        """
        encoder, enc_flags = await self._detect_h264_encoder()

        vf_parts: list[str] = []
        if target_width and target_height:
            vf_parts.append(
                f"scale={target_width}:{target_height}:"
                "force_original_aspect_ratio=decrease,"
                f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2"
            )

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i", input_path,
            "-t", str(duration),
        ]
        if vf_parts:
            cmd.extend(["-vf", ",".join(vf_parts)])
        cmd.extend([
            "-c:v", encoder,
            *enc_flags,
            "-c:a", "aac",
            "-b:a", "128k",
            output_path,
        ])
        try:
            await self._run_command(cmd)
            return {"success": True, "output_path": output_path}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def loop_extend_clip(
        self,
        input_path: str,
        output_path: str,
        target_duration: float,
        target_width: int | None = None,
        target_height: int | None = None,
    ) -> dict[str, Any]:
        """Loop source footage to fill a target duration.

        Uses FFmpeg ``-stream_loop -1`` to loop the source and ``-t``
        to cut at the desired length.

        Args:
            input_path: Input video path.
            output_path: Output video path.
            target_duration: Desired output duration in seconds.
            target_width: Optional target width for resolution normalization.
            target_height: Optional target height for resolution normalization.

        Returns:
            Result dict with success status.
        """
        encoder, enc_flags = await self._detect_h264_encoder()

        vf_parts: list[str] = []
        if target_width and target_height:
            vf_parts.append(
                f"scale={target_width}:{target_height}:"
                "force_original_aspect_ratio=decrease,"
                f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2"
            )

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-stream_loop", "-1",
            "-i", input_path,
            "-t", str(target_duration),
        ]
        if vf_parts:
            cmd.extend(["-vf", ",".join(vf_parts)])
        cmd.extend([
            "-c:v", encoder,
            *enc_flags,
            "-an",
            output_path,
        ])

        try:
            await self._run_command(cmd)
            return {"success": True, "output_path": output_path}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def add_background_music(
        self,
        video_path: str,
        music_path: str,
        output_path: str,
        music_volume: float = 0.35,
    ) -> dict[str, Any]:
        """Mix background music into a video with sidechain compression.

        The video's existing audio (voiceover) is kept at full volume.
        Music is loudness-normalized then ducked under VO via
        sidechaincompress so the voice stays clear while music fills gaps.

        Args:
            video_path: Input video (with VO audio).
            music_path: Background music file path.
            output_path: Output video path.
            music_volume: Base music volume before ducking (default 0.35).

        Returns:
            Result dict with success status.
        """
        filter_str = (
            "[0:a]volume=1.0,asplit=2[vo][voref];"
            f"[1:a]loudnorm=I=-14:TP=-1:LRA=11,volume={music_volume}[music];"
            "[music][voref]sidechaincompress="
            "threshold=0.02:ratio=6:attack=50:release=500[musicduck];"
            "[vo][musicduck]amix=inputs=2:duration=first:normalize=0[out]"
        )

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i", video_path,
            "-i", music_path,
            "-filter_complex", filter_str,
            "-map", "0:v",
            "-map", "[out]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            output_path,
        ]

        try:
            await self._run_command(cmd)
            return {"success": True, "output_path": output_path}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def mix_audio(
        self,
        audio_config: dict[str, Any],
        output_path: str,
    ) -> dict[str, Any]:
        """
        Mix audio tracks (voiceover + music).

        Args:
            audio_config: Audio mixing configuration
            output_path: Output path for mixed audio

        Returns:
            Mixing result
        """
        vo_path = audio_config.get("voiceover_path", "")
        music_path = audio_config.get("music_path", "")
        vo_volume = audio_config.get("vo_volume", 1.0)
        music_volume = audio_config.get("music_volume", 0.15)
        duck_during_vo = audio_config.get("duck_during_vo", True)

        tracks_mixed = 0
        inputs = []
        filters = []

        if vo_path and os.path.exists(vo_path):
            inputs.extend(["-i", vo_path])
            filters.append(f"[0:a]volume={vo_volume}[vo]")
            tracks_mixed += 1

        if music_path and os.path.exists(music_path):
            inputs.extend(["-i", music_path])
            music_idx = 1 if vo_path else 0
            filters.append(f"[{music_idx}:a]volume={music_volume}[music]")
            tracks_mixed += 1

        if tracks_mixed == 0:
            return {"error": "No valid audio tracks provided", "tracks_mixed": 0}

        if tracks_mixed == 2:
            if duck_during_vo:
                # Sidechain compression for ducking
                filter_str = (
                    f"[0:a]volume={vo_volume},asplit=2[vo][voref];"
                    f"[1:a]volume={music_volume}[music];"
                    "[music][voref]sidechaincompress=threshold=0.02:ratio=6:attack=50:release=500[musicduck];"
                    "[vo][musicduck]amix=inputs=2:duration=longest[out]"
                )
            else:
                filter_str = (
                    f"[0:a]volume={vo_volume}[vo];"
                    f"[1:a]volume={music_volume}[music];"
                    "[vo][music]amix=inputs=2:duration=longest[out]"
                )

            cmd = [
                self.ffmpeg_path,
                "-y",
                *inputs,
                "-filter_complex", filter_str,
                "-map", "[out]",
                "-c:a", "aac",
                "-b:a", "192k",
                output_path,
            ]
        else:
            # Single track
            cmd = [
                self.ffmpeg_path,
                "-y",
                *inputs,
                "-c:a", "aac",
                "-b:a", "192k",
                output_path,
            ]

        try:
            await self._run_command(cmd)
            return {"success": True, "tracks_mixed": tracks_mixed}
        except Exception as e:
            return {"error": str(e), "tracks_mixed": 0}

    async def normalize_audio(
        self,
        audio_path: str,
        target_lufs: float = -14.0,
        output_path: str | None = None,
    ) -> dict[str, Any]:
        """
        Normalize audio levels to target LUFS.

        Args:
            audio_path: Input audio path
            target_lufs: Target loudness in LUFS (default: -14 for social)
            output_path: Output path (defaults to overwrite input)

        Returns:
            Normalization result
        """
        if output_path is None:
            output_path = audio_path.replace(".mp3", "_normalized.mp3")

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i", audio_path,
            "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11",
            "-ar", "44100",
            "-c:a", "aac",
            "-b:a", "192k",
            output_path,
        ]

        try:
            await self._run_command(cmd)
            return {"normalized": True, "target_lufs": target_lufs, "output_path": output_path}
        except Exception as e:
            return {"normalized": False, "error": str(e)}

    async def export(
        self,
        input_path: str,
        output_path: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Export video with specified settings.

        Args:
            input_path: Input video path
            output_path: Output video path
            config: Export configuration

        Returns:
            Export result
        """
        video_format = config.get("format", "mp4")
        codec = config.get("codec", "h264")
        resolution = config.get("resolution", (1080, 1920))
        fps = config.get("fps", 30)
        bitrate = config.get("bitrate", "8M")

        width, height = resolution

        # Detect best encoder for h264
        if codec == "h264":
            video_codec, enc_flags = await self._detect_h264_encoder()
        else:
            codec_map = {
                "h265": "libx265",
                "vp9": "libvpx-vp9",
            }
            video_codec = codec_map.get(codec, "libx264")
            enc_flags = []

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i", input_path,
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
            "-r", str(fps),
            "-c:v", video_codec,
            *enc_flags,
            "-b:v", bitrate,
            "-c:a", "copy",
            "-movflags", "+faststart",  # For web streaming
            output_path,
        ]

        try:
            await self._run_command(cmd)

            # Get file info
            file_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0

            return {
                "format": video_format,
                "codec": codec,
                "resolution": resolution,
                "fps": fps,
                "bitrate": bitrate,
                "file_size_bytes": file_size,
                "output_path": output_path,
            }
        except Exception as e:
            return {"error": str(e)}

    async def add_text_overlay(
        self,
        input_path: str,
        output_path: str,
        text: str,
        position: TextPosition,
        start_time: float,
        duration: float,
        font_size: int = 48,
        font_color: str = "white",
        animation: TextAnimation = TextAnimation.FADE,
        safe_zone: SafeZone | None = None,
    ) -> dict[str, Any]:
        """
        Add text overlay to video.

        Args:
            input_path: Input video path
            output_path: Output video path
            text: Text to overlay
            position: Position on screen
            start_time: When text appears (seconds)
            duration: How long text shows (seconds)
            font_size: Font size
            font_color: Font color
            animation: Animation type
            safe_zone: Optional platform safe zone for position offsets

        Returns:
            Result
        """
        x, y = self.POSITION_COORDS.get(
            position, self.POSITION_COORDS[TextPosition.BOTTOM_CENTER]
        )

        # Apply safe zone offsets if provided
        if safe_zone is not None:
            if position in (TextPosition.TOP_CENTER, TextPosition.TOP_LEFT, TextPosition.TOP_RIGHT):
                y = str(safe_zone.top + int(y) if y.isdigit() else f"{y}+{safe_zone.top}")
            elif position in (
                TextPosition.BOTTOM_CENTER,
                TextPosition.BOTTOM_LEFT,
                TextPosition.BOTTOM_RIGHT,
            ):
                y = f"h-text_h-{150 + safe_zone.bottom}"
            if safe_zone.left and position in (TextPosition.TOP_LEFT, TextPosition.BOTTOM_LEFT):
                x = str(safe_zone.left + int(x) if x.isdigit() else f"{x}+{safe_zone.left}")
            if safe_zone.right and position in (TextPosition.TOP_RIGHT, TextPosition.BOTTOM_RIGHT):
                x = f"w-text_w-{50 + safe_zone.right}"

        # Build enable expression for timing
        end_time = start_time + duration
        enable = f"between(t,{start_time},{end_time})"

        # Build alpha expression for animation
        if animation == TextAnimation.FADE:
            fade_duration = 0.3
            # Alpha expression for fade animation (reserved for future use)
            _ = (
                f"if(lt(t,{start_time}),0,"
                f"if(lt(t,{start_time + fade_duration}),"
                f"(t-{start_time})/{fade_duration},"
                f"if(lt(t,{end_time - fade_duration}),1,"
                f"({end_time}-t)/{fade_duration})))"
            )

        # Escape text for FFmpeg
        escaped_text = text.replace("'", "'\\''").replace(":", "\\:")

        drawtext_filter = (
            f"drawtext=text='{escaped_text}':"
            f"fontfile='{self.font_path}':"
            f"fontsize={font_size}:"
            f"fontcolor={font_color}:"
            f"x={x}:y={y}:"
            f"enable='{enable}'"
        )

        encoder, enc_flags = await self._detect_h264_encoder()
        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i", input_path,
            "-vf", drawtext_filter,
            "-c:v", encoder,
            *enc_flags,
            "-c:a", "copy",
            output_path,
        ]

        try:
            await self._run_command(cmd)
            return {"success": True, "text_added": text}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def overlay_audio_tracks(
        self,
        video_path: str,
        audio_tracks: list[dict[str, Any]],
        output_path: str,
    ) -> dict[str, Any]:
        """
        Overlay multiple audio tracks with time offsets onto a video.

        Args:
            video_path: Input video path
            audio_tracks: List of dicts with 'path' and 'start_time' keys
            output_path: Output video path with audio

        Returns:
            Result dict with success status
        """
        # Filter to only existing, non-empty files
        valid_tracks = [
            t for t in audio_tracks
            if t.get("path")
            and os.path.exists(t["path"])
            and os.path.getsize(t["path"]) > 0
        ]

        if not valid_tracks:
            return {"success": False, "error": "No valid audio tracks provided"}

        # Build FFmpeg inputs: video first, then each audio
        inputs = ["-i", video_path]
        for track in valid_tracks:
            inputs.extend(["-i", track["path"]])

        # Build filter_complex: adelay each audio, then amix
        filters = []
        mix_labels = []
        for i, track in enumerate(valid_tracks):
            audio_idx = i + 1  # 0 is the video
            delay_ms = int(track.get("start_time", 0.0) * 1000)
            label = f"a{i}"
            if delay_ms > 0:
                filters.append(f"[{audio_idx}:a]adelay={delay_ms}|{delay_ms}[{label}]")
            else:
                filters.append(f"[{audio_idx}:a]acopy[{label}]")
            mix_labels.append(f"[{label}]")

        if len(valid_tracks) > 1:
            mix_input = "".join(mix_labels)
            filters.append(
                f"{mix_input}amix=inputs={len(valid_tracks)}"
                ":duration=longest:normalize=0:dropout_transition=0[aout]"
            )
            map_audio = ["-map", "[aout]"]
        else:
            map_audio = ["-map", f"[{mix_labels[0].strip('[]')}]"]

        filter_str = ";".join(filters)

        cmd = [
            self.ffmpeg_path,
            "-y",
            *inputs,
            "-filter_complex", filter_str,
            "-map", "0:v",
            *map_audio,
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            output_path,
        ]

        try:
            await self._run_command(cmd)
            return {"success": True, "output_path": output_path}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _render_subtitle_frame(
        self,
        seg: Any,
        index: int,
        video_width: int = 1080,
        video_height: int = 1920,
        font_size: int | None = None,
        subtitle_config: Any = None,
    ) -> str:
        """
        Render a single subtitle segment as a transparent PNG.

        When subtitle_config is provided, uses lower-third positioning,
        shadow, background pill, and scaled font size. Otherwise falls
        back to legacy centered rendering.

        Args:
            seg: SubtitleSegment with .text attribute
            index: Segment index for filename
            video_width: Video width
            video_height: Video height
            font_size: Font size (legacy, overridden by config)
            subtitle_config: SubtitleConfig for visual settings

        Returns:
            Path to the rendered PNG file
        """
        from PIL import Image, ImageDraw, ImageFont

        # Resolve config
        if subtitle_config is not None:
            effective_font_size = int(video_width * subtitle_config.font_size_ratio)
            outline_width = subtitle_config.outline_width
            shadow_offset = subtitle_config.shadow_offset
            bg_enabled = subtitle_config.bg_enabled
            bg_color = subtitle_config.bg_color
            bg_padding = subtitle_config.bg_padding
            start_y_pos = int(video_height * subtitle_config.position_y_ratio)
        else:
            effective_font_size = font_size if font_size is not None else 48
            outline_width = 3
            shadow_offset = 0
            bg_enabled = False
            bg_color = (0, 0, 0, 160)
            bg_padding = 16
            start_y_pos = None  # will be centered

        img = Image.new("RGBA", (video_width, video_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.truetype(self.font_path, effective_font_size)
        except OSError:
            font = ImageFont.load_default()

        margin = 60
        max_text_width = video_width - 2 * margin

        # Word-wrap text to fit within max_text_width
        words = seg.text.split()
        lines: list[str] = []
        current_line = ""
        for word in words:
            test_line = f"{current_line} {word}".strip()
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if bbox[2] - bbox[0] <= max_text_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)

        if not lines:
            lines = [seg.text]

        # Measure total block height
        line_spacing = 8
        line_heights = []
        line_widths = []
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            line_widths.append(bbox[2] - bbox[0])
            line_heights.append(bbox[3] - bbox[1])

        total_height = sum(line_heights) + line_spacing * (len(lines) - 1)

        start_y = start_y_pos if start_y_pos is not None else (video_height - total_height) // 2

        # Draw background pill if enabled
        if bg_enabled:
            max_line_width = max(line_widths) if line_widths else 0
            pill_x1 = (video_width - max_line_width) // 2 - bg_padding
            pill_y1 = start_y - bg_padding
            pill_x2 = (video_width + max_line_width) // 2 + bg_padding
            pill_y2 = start_y + total_height + bg_padding
            draw.rounded_rectangle(
                [pill_x1, pill_y1, pill_x2, pill_y2],
                radius=12,
                fill=bg_color,
            )

        # Resolve colors from config
        if subtitle_config is not None:
            text_color = getattr(subtitle_config, "text_color", (255, 255, 255, 255))
            shadow_color = getattr(subtitle_config, "shadow_color", (0, 0, 0, 180))
            shadow_blur_radius = getattr(subtitle_config, "shadow_blur_radius", 0)
        else:
            text_color = (255, 255, 255, 255)
            shadow_color = (0, 0, 0, 180)
            shadow_blur_radius = 0

        # Draw shadow on separate layer if blur is needed
        if shadow_offset > 0 and shadow_blur_radius > 0:
            from PIL import ImageFilter

            shadow_layer = Image.new("RGBA", (video_width, video_height), (0, 0, 0, 0))
            shadow_draw = ImageDraw.Draw(shadow_layer)
            sy = start_y
            for j, line in enumerate(lines):
                sx = (video_width - line_widths[j]) // 2
                shadow_draw.text(
                    (sx + shadow_offset, sy + shadow_offset), line,
                    font=font, fill=shadow_color,
                )
                sy += line_heights[j] + line_spacing
            shadow_layer = shadow_layer.filter(
                ImageFilter.GaussianBlur(radius=shadow_blur_radius)
            )
            img = Image.alpha_composite(img, shadow_layer)
            draw = ImageDraw.Draw(img)

        # Draw each line centered
        current_y = start_y
        for j, line in enumerate(lines):
            x = (video_width - line_widths[j]) // 2

            # Draw hard shadow (only when blur is 0)
            if shadow_offset > 0 and shadow_blur_radius == 0:
                draw.text(
                    (x + shadow_offset, current_y + shadow_offset), line,
                    font=font, fill=shadow_color,
                )

            # Draw outline
            if outline_width > 0:
                for dx in range(-outline_width, outline_width + 1):
                    for dy in range(-outline_width, outline_width + 1):
                        if dx != 0 or dy != 0:
                            draw.text(
                                (x + dx, current_y + dy), line,
                                font=font, fill=(0, 0, 0, 255),
                            )

            # Draw text
            draw.text((x, current_y), line, font=font, fill=text_color)
            current_y += line_heights[j] + line_spacing

        sub_dir = self.output_dir / "sub_frames"
        sub_dir.mkdir(parents=True, exist_ok=True)
        png_path = str(sub_dir / f"sub_{index:03d}.png")
        img.save(png_path)
        return png_path

    async def burn_subtitles_overlay(
        self,
        input_path: str,
        output_path: str,
        segments: list[Any],
        video_width: int = 1080,
        video_height: int = 1920,
        font_size: int = 48,
        subtitle_config: Any = None,
    ) -> dict[str, Any]:
        """
        Burn subtitles using Pillow-rendered PNGs + FFmpeg overlay filter.

        Works without libass/subtitles filter. Renders each subtitle segment
        as a transparent PNG, then overlays with timed enable expressions.

        Args:
            input_path: Input video path
            output_path: Output video path
            segments: List of SubtitleSegment objects
            video_width: Video width for text rendering
            video_height: Video height for text rendering
            font_size: Font size for subtitle text

        Returns:
            Result dict with success status
        """
        if not segments:
            return {"success": False, "error": "No subtitle segments"}

        # Render each segment as a transparent PNG
        png_paths: list[str] = []
        for i, seg in enumerate(segments):
            png_path = self._render_subtitle_frame(
                seg, index=i,
                video_width=video_width, video_height=video_height,
                font_size=font_size,
                subtitle_config=subtitle_config,
            )
            png_paths.append(png_path)

        # Build FFmpeg command with overlay filters
        inputs = ["-i", input_path]
        for png_path in png_paths:
            inputs.extend(["-i", png_path])

        # Build filter chain: overlay each PNG with timing
        filter_parts = []
        prev_label = "0:v"
        for i, seg in enumerate(segments):
            input_idx = i + 1
            out_label = f"v{i}"
            enable = f"between(t,{seg.start_time},{seg.end_time})"
            filter_parts.append(
                f"[{prev_label}][{input_idx}:v]overlay=0:0:enable='{enable}'[{out_label}]"
            )
            prev_label = out_label

        filter_str = ";".join(filter_parts)

        encoder, enc_flags = await self._detect_h264_encoder()
        cmd = [
            self.ffmpeg_path,
            "-y",
            *inputs,
            "-filter_complex", filter_str,
            "-map", f"[{prev_label}]",
            "-map", "0:a?",
            "-c:v", encoder,
            *enc_flags,
            "-c:a", "copy",
            output_path,
        ]

        try:
            await self._run_command(cmd)
            return {"success": True, "output_path": output_path}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def burn_subtitles(
        self,
        input_path: str,
        output_path: str,
        srt_path: str,
        style: Any = None,
    ) -> dict[str, Any]:
        """
        Burn SRT subtitles into video using FFmpeg.

        Args:
            input_path: Input video path
            output_path: Output video path
            srt_path: Path to SRT subtitle file
            style: SubtitleStyle for font/color configuration

        Returns:
            Result dict with success status
        """
        from .subtitle_generator import SubtitleStyle, build_ffmpeg_subtitle_filter

        if style is None:
            style = SubtitleStyle()

        vf = build_ffmpeg_subtitle_filter(style, srt_path)

        encoder, enc_flags = await self._detect_h264_encoder()
        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i", input_path,
            "-vf", vf,
            "-c:v", encoder,
            *enc_flags,
            "-c:a", "copy",
            output_path,
        ]

        try:
            await self._run_command(cmd)
            return {"success": True, "output_path": output_path}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def export_for_platform(
        self,
        input_path: str,
        output_path: str,
        platform: str,
    ) -> dict[str, Any]:
        """
        Export video with platform-specific settings.

        Looks up PlatformFormat for resolution/aspect ratio
        and delegates to export().

        Args:
            input_path: Input video path
            output_path: Output video path
            platform: Platform identifier (e.g. "tiktok")

        Returns:
            Export result dict

        Raises:
            ValueError: If unknown platform
        """
        fmt = get_platform_format(platform)

        config = {
            "format": "mp4",
            "codec": "h264",
            "resolution": (fmt.width, fmt.height),
            "fps": 30,
            "bitrate": "8M",
        }

        return await self.export(input_path, output_path, config=config)

    async def get_video_info(self, video_path: str) -> dict[str, Any]:
        """
        Get video file information.

        Args:
            video_path: Path to video file

        Returns:
            Video metadata
        """
        cmd = [
            self.ffprobe_path,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            video_path,
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, _ = await process.communicate()

        if process.returncode != 0:
            return {"error": "Failed to probe video"}

        import json
        data = json.loads(stdout.decode())

        # Extract relevant info
        video_stream = next(
            (s for s in data.get("streams", []) if s["codec_type"] == "video"),
            {},
        )
        audio_stream = next(
            (s for s in data.get("streams", []) if s["codec_type"] == "audio"),
            None,
        )

        format_info = data.get("format", {})

        return {
            "duration": float(format_info.get("duration", 0)),
            "width": video_stream.get("width", 0),
            "height": video_stream.get("height", 0),
            "fps": eval(video_stream.get("r_frame_rate", "30/1")),
            "codec": video_stream.get("codec_name", ""),
            "has_audio": audio_stream is not None,
            "file_size": int(format_info.get("size", 0)),
            "bitrate": int(format_info.get("bit_rate", 0)),
        }

    def _generate_circle_mask(
        self,
        width: int,
        height: int,
        output_path: str,
    ) -> str:
        """Generate a circle mask image (white ellipse on black).

        Args:
            width: Image width.
            height: Image height.
            output_path: Path to save the mask PNG.

        Returns:
            The output_path.
        """
        from PIL import Image, ImageDraw

        img = Image.new("L", (width, height), 0)
        draw = ImageDraw.Draw(img)
        draw.ellipse([0, 0, width - 1, height - 1], fill=255)
        img.save(output_path)
        return output_path

    async def remove_background(
        self,
        video_path: str,
        output_dir: str,
    ) -> str:
        """Extract alpha mask from the first frame of a video using rembg.

        1. Extract first frame via FFmpeg.
        2. Run rembg on the frame to get RGBA.
        3. Save the alpha channel as a grayscale mask PNG.

        Args:
            video_path: Path to avatar video.
            output_dir: Directory for intermediate files.

        Returns:
            Path to the grayscale mask PNG.
        """
        from PIL import Image

        output = Path(output_dir)
        frame_path = str(output / "frame_0.png")

        # Extract first frame
        cmd = [
            self.ffmpeg_path, "-y",
            "-i", video_path,
            "-vframes", "1",
            frame_path,
        ]
        await self._run_command(cmd)

        # Lazy import rembg
        from rembg import remove

        frame = Image.open(frame_path).convert("RGB")
        rgba = remove(frame)

        # Extract alpha channel as grayscale mask
        alpha = rgba.split()[-1]
        mask_path = str(output / "bg_mask.png")
        alpha.save(mask_path)
        return mask_path

    async def concat_audio_files(
        self,
        audio_paths: list[str],
        output_path: str,
    ) -> dict[str, Any]:
        """Concatenate multiple audio files into one.

        Single-file case copies without invoking FFmpeg.

        Args:
            audio_paths: List of audio file paths.
            output_path: Output audio path.

        Returns:
            Result dict with success status and output_path.
        """
        if len(audio_paths) == 1:
            # Transcode single file to ensure correct container format
            cmd = [
                self.ffmpeg_path, "-y",
                "-i", audio_paths[0],
                "-c:a", "aac", "-b:a", "192k",
                output_path,
            ]
            await self._run_command(cmd)
            return {"success": True, "output_path": output_path}

        # Build concat filter for multiple files
        inputs: list[str] = []
        for path in audio_paths:
            inputs.extend(["-i", path])

        n = len(audio_paths)
        filter_inputs = "".join(f"[{i}:a]" for i in range(n))
        filter_str = f"{filter_inputs}concat=n={n}:v=0:a=1[out]"

        cmd = [
            self.ffmpeg_path, "-y",
            *inputs,
            "-filter_complex", filter_str,
            "-map", "[out]",
            "-c:a", "aac", "-b:a", "192k",
            output_path,
        ]
        await self._run_command(cmd)
        return {"success": True, "output_path": output_path}

    async def overlay_pip_avatar(
        self,
        video_path: str,
        avatar_path: str,
        output_path: str,
        video_width: int = 1080,
        video_height: int = 1920,
        overlay_size: float = 0.30,
        position: str = "bottom_right",
        margin: int = 40,
        circle_crop: bool = True,
    ) -> dict[str, Any]:
        """Overlay a background-removed avatar as PIP on the video.

        1. Generate alpha mask via remove_background().
        2. Optionally combine with circle mask.
        3. FFmpeg: scale avatar, apply alphamerge, overlay on video.

        Args:
            video_path: Base video path.
            avatar_path: Avatar video path.
            output_path: Output video path.
            video_width: Video width for position calculation.
            video_height: Video height for position calculation.
            overlay_size: Avatar width as fraction of video width.
            position: Overlay position (e.g. "bottom_right").
            margin: Pixels from edge.
            circle_crop: Whether to circle-crop the avatar.

        Returns:
            Result dict with success status.
        """
        from PIL import Image, ImageChops

        pip_w = int(video_width * overlay_size)
        pip_h = pip_w  # Square avatar

        # Step 1: Remove background → mask PNG
        mask_dir = str(self.output_dir / "pip_masks")
        Path(mask_dir).mkdir(parents=True, exist_ok=True)
        mask_path = await self.remove_background(avatar_path, mask_dir)

        # Step 2: Optionally combine with circle mask
        if circle_crop:
            circle_path = str(Path(mask_dir) / "circle_mask.png")
            self._generate_circle_mask(pip_w, pip_h, circle_path)

            # AND the two masks together (resize bg mask to pip size first)
            bg_mask = Image.open(mask_path).convert("L").resize((pip_w, pip_h))
            circle_mask = Image.open(circle_path).convert("L")
            combined = ImageChops.darker(bg_mask, circle_mask)
            combined_path = str(Path(mask_dir) / "combined_mask.png")
            combined.save(combined_path)
            mask_path = combined_path

        # Step 3: Compute position
        if position == "bottom_right":
            x = video_width - pip_w - margin
            y = video_height - pip_h - margin
        elif position == "bottom_left":
            x = margin
            y = video_height - pip_h - margin
        elif position == "top_right":
            x = video_width - pip_w - margin
            y = margin
        else:  # top_left
            x = margin
            y = margin

        # Step 4: FFmpeg filter chain
        escaped_mask = mask_path.replace("'", "'\\''")
        filter_str = (
            f"[1:v]scale={pip_w}:{pip_h}[av];"
            f"movie='{escaped_mask}',scale={pip_w}:{pip_h},"
            f"loop=-1:size=1:start=0[mk];"
            f"[av][mk]alphamerge[alpha];"
            f"[0:v][alpha]overlay={x}:{y}:shortest=1[out]"
        )

        encoder, enc_flags = await self._detect_h264_encoder()
        cmd = [
            self.ffmpeg_path, "-y",
            "-i", video_path,
            "-i", avatar_path,
            "-filter_complex", filter_str,
            "-map", "[out]",
            "-map", "0:a?",
            "-c:v", encoder,
            *enc_flags,
            "-c:a", "copy",
            output_path,
        ]

        try:
            await self._run_command(cmd)
            return {"success": True, "output_path": output_path}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def create_thumbnail(
        self,
        video_path: str,
        output_path: str,
        timestamp: float = 0.0,
    ) -> dict[str, Any]:
        """
        Create thumbnail from video frame.

        Args:
            video_path: Source video path
            output_path: Output thumbnail path
            timestamp: Timestamp to capture (seconds)

        Returns:
            Result
        """
        cmd = [
            self.ffmpeg_path,
            "-y",
            "-ss", str(timestamp),
            "-i", video_path,
            "-vframes", "1",
            "-q:v", "2",
            output_path,
        ]

        try:
            await self._run_command(cmd)
            return {"success": True, "path": output_path, "timestamp": timestamp}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def trim_silence(
        self,
        input_path: str,
        output_path: str,
        threshold_db: float = -40.0,
        min_silence_duration: float = 0.1,
    ) -> dict[str, Any]:
        """Trim silence from beginning and end of audio file.

        Args:
            input_path: Input audio path.
            output_path: Output audio path.
            threshold_db: Volume threshold for silence detection (dB).
            min_silence_duration: Minimum silence duration to remove (seconds).

        Returns:
            Result dict with success status.
        """
        # silenceremove filter: remove silence from start and end
        af_filter = (
            f"silenceremove=start_periods=1:start_duration={min_silence_duration}:"
            f"start_threshold={threshold_db}dB:"
            f"stop_periods=1:stop_duration={min_silence_duration}:"
            f"stop_threshold={threshold_db}dB"
        )

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i", input_path,
            "-af", af_filter,
            "-c:a", "libmp3lame",
            "-b:a", "192k",
            output_path,
        ]

        try:
            await self._run_command(cmd)
            return {"success": True, "output_path": output_path}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def speed_up_audio(
        self,
        input_path: str,
        output_path: str,
        speed_factor: float = 1.15,
    ) -> dict[str, Any]:
        """Speed up audio file by a factor.

        Args:
            input_path: Input audio path.
            output_path: Output audio path.
            speed_factor: Speed multiplier (1.15 = 15% faster).

        Returns:
            Result dict with success status.
        """
        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i", input_path,
            "-af", f"atempo={speed_factor}",
            "-c:a", "libmp3lame",
            "-b:a", "192k",
            output_path,
        ]

        try:
            await self._run_command(cmd)
            return {"success": True, "output_path": output_path}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def process_voice_audio(
        self,
        input_path: str,
        output_path: str,
        speed_factor: float = 1.15,
    ) -> dict[str, Any]:
        """Process voice audio: trim silence + speed up.

        Combines silence trimming and speed adjustment in one pass.

        Args:
            input_path: Input audio path.
            output_path: Output audio path.
            speed_factor: Speed multiplier (1.15 = 15% faster).

        Returns:
            Result dict with success status and duration.
        """
        # Combined filter: silence removal + speed up
        af_filter = (
            "silenceremove=start_periods=1:start_duration=0.1:"
            "start_threshold=-40dB:"
            "stop_periods=1:stop_duration=0.1:"
            f"stop_threshold=-40dB,atempo={speed_factor}"
        )

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i", input_path,
            "-af", af_filter,
            "-c:a", "libmp3lame",
            "-b:a", "192k",
            output_path,
        ]

        try:
            await self._run_command(cmd)
            # Get duration of processed file
            duration = await self._get_audio_duration(output_path)
            return {"success": True, "output_path": output_path, "duration": duration}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _get_audio_duration(self, audio_path: str) -> float:
        """Get duration of audio file in seconds."""
        cmd = [
            self.ffprobe_path,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path,
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()

        try:
            return float(stdout.decode().strip())
        except (ValueError, AttributeError):
            return 0.0
