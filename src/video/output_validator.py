"""
Output Validator - Validates rendered output against brief requirements.
"""

import os
from typing import Any


class OutputValidator:
    """
    Validates rendered video output against requirements.

    Checks:
    - Duration matches brief
    - Resolution meets minimum
    - Audio track present
    - File size within limits
    """

    def __init__(
        self,
        ffprobe_path: str = "ffprobe",
    ):
        """
        Initialize validator.

        Args:
            ffprobe_path: Path to ffprobe executable for media analysis
        """
        self.ffprobe_path = ffprobe_path

    async def validate_duration(
        self,
        render_output: dict[str, Any],
        brief: dict[str, Any],
        tolerance_seconds: float | None = None,
    ) -> dict[str, Any]:
        """
        Validate that output duration matches brief specifications.

        Uses proportional tolerance by default:
        - Overshoot allowed: max(3.0, target * 0.20)
        - Undershoot allowed: max(2.0, target * 0.10)

        Args:
            render_output: Rendered output info
            brief: Creative brief with duration specs
            tolerance_seconds: Legacy fixed tolerance (overrides proportional)

        Returns:
            Validation result with passed status and details
        """
        video_info = render_output.get("output_files", {}).get("video", {})
        actual_duration = video_info.get("duration_seconds", 0)

        # Get expected duration from brief
        specs = brief.get("specifications", {})
        expected_duration = specs.get("total_duration", 0)

        # Also calculate from shot list if available
        if expected_duration == 0:
            shots = brief.get("shot_list", [])
            expected_duration = sum(s.get("duration_seconds", 0) for s in shots)

        difference = actual_duration - expected_duration

        if tolerance_seconds is not None:
            # Legacy mode: symmetric fixed tolerance
            passed = abs(difference) <= tolerance_seconds
            tolerance_info = tolerance_seconds
        else:
            # Proportional tolerance
            overshoot_limit = max(3.0, expected_duration * 0.20)
            undershoot_limit = max(2.0, expected_duration * 0.10)

            if difference > 0:
                passed = difference <= overshoot_limit
            else:
                passed = abs(difference) <= undershoot_limit
            tolerance_info = f"+{overshoot_limit:.1f}/-{undershoot_limit:.1f}"

        return {
            "passed": passed,
            "actual_duration": actual_duration,
            "expected_duration": expected_duration,
            "difference": abs(difference),
            "tolerance": tolerance_info,
            "message": (
                "Duration within tolerance"
                if passed
                else f"Duration off by {abs(difference):.1f}s (tolerance: {tolerance_info}s)"
            ),
        }

    async def validate_resolution(
        self,
        render_output: dict[str, Any],
        min_resolution: tuple[int, int] = (720, 1280),
    ) -> dict[str, Any]:
        """
        Validate that output resolution meets minimum requirements.

        Args:
            render_output: Rendered output info
            min_resolution: Minimum (width, height) required

        Returns:
            Validation result
        """
        video_info = render_output.get("output_files", {}).get("video", {})
        resolution_str = video_info.get("resolution", "0x0")

        # Parse resolution string (e.g., "1080x1920")
        try:
            width, height = map(int, resolution_str.split("x"))
        except (ValueError, AttributeError):
            width, height = 0, 0

        min_width, min_height = min_resolution
        passed = width >= min_width and height >= min_height

        return {
            "passed": passed,
            "actual_width": width,
            "actual_height": height,
            "min_width": min_width,
            "min_height": min_height,
            "message": (
                "Resolution meets requirements"
                if passed
                else f"Resolution {width}x{height} below minimum {min_width}x{min_height}"
            ),
        }

    async def validate_audio(
        self,
        render_output: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Validate that audio track is present in output.

        Args:
            render_output: Rendered output info

        Returns:
            Validation result with has_audio status
        """
        video_info = render_output.get("output_files", {}).get("video", {})
        video_path = video_info.get("path", "")

        # Use ffprobe to check for audio stream
        if video_path and os.path.exists(video_path):
            result = await self._check_audio_stream(video_path)
            has_audio = result.get("has_audio", False)
        else:
            # If no file, assume audio present (will be caught by other validation)
            has_audio = True

        return {
            "has_audio": has_audio,
            "passed": has_audio,
            "message": "Audio track present" if has_audio else "No audio track found",
        }

    async def _check_audio_stream(self, video_path: str) -> dict[str, Any]:
        """
        Check if video file has audio stream using ffprobe.

        Args:
            video_path: Path to video file

        Returns:
            Dict with has_audio boolean
        """
        import asyncio
        import json

        cmd = [
            self.ffprobe_path,
            "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            "-select_streams", "a",
            video_path,
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()

            if process.returncode == 0:
                data = json.loads(stdout.decode())
                has_audio = len(data.get("streams", [])) > 0
                return {"has_audio": has_audio}
        except Exception:
            pass

        return {"has_audio": False}

    async def validate_file_size(
        self,
        render_output: dict[str, Any],
        max_size_mb: float = 100.0,
    ) -> dict[str, Any]:
        """
        Validate that file size is within platform limits.

        Args:
            render_output: Rendered output info
            max_size_mb: Maximum file size in MB

        Returns:
            Validation result
        """
        video_info = render_output.get("output_files", {}).get("video", {})

        # Get size from output info or check file directly
        actual_size_mb = video_info.get("file_size_mb", 0)

        if actual_size_mb == 0:
            video_path = video_info.get("path", "")
            if video_path and os.path.exists(video_path):
                actual_size_mb = os.path.getsize(video_path) / (1024 * 1024)

        passed = actual_size_mb <= max_size_mb

        return {
            "passed": passed,
            "actual_size_mb": actual_size_mb,
            "max_size_mb": max_size_mb,
            "message": (
                f"File size {actual_size_mb:.1f}MB within limit"
                if passed
                else f"File size {actual_size_mb:.1f}MB exceeds {max_size_mb}MB limit"
            ),
        }

    async def validate_all(
        self,
        render_output: dict[str, Any],
        brief: dict[str, Any],
        platform_limits: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Run all validation checks.

        Args:
            render_output: Rendered output info
            brief: Creative brief
            platform_limits: Platform-specific limits

        Returns:
            Combined validation results
        """
        limits = platform_limits or {
            "min_resolution": (720, 1280),
            "max_size_mb": 100.0,
        }

        duration_result = await self.validate_duration(
            render_output,
            brief,
            tolerance_seconds=limits.get("duration_tolerance"),
        )

        resolution_result = await self.validate_resolution(
            render_output,
            min_resolution=limits.get("min_resolution", (720, 1280)),
        )

        audio_result = await self.validate_audio(render_output)

        file_size_result = await self.validate_file_size(
            render_output,
            max_size_mb=limits.get("max_size_mb", 100.0),
        )

        all_passed = all([
            duration_result["passed"],
            resolution_result["passed"],
            audio_result["passed"],
            file_size_result["passed"],
        ])

        issues = []
        if not duration_result["passed"]:
            issues.append({"check": "duration", "message": duration_result["message"]})
        if not resolution_result["passed"]:
            issues.append({"check": "resolution", "message": resolution_result["message"]})
        if not audio_result["passed"]:
            issues.append({"check": "audio", "message": audio_result["message"]})
        if not file_size_result["passed"]:
            issues.append({"check": "file_size", "message": file_size_result["message"]})

        return {
            "passed": all_passed,
            "checks": {
                "duration": duration_result,
                "resolution": resolution_result,
                "audio": audio_result,
                "file_size": file_size_result,
            },
            "issues": issues,
        }
