"""Telegram CTA video compositor.

Composites a screen recording into an iPhone frame with optional pointing finger.
"""

import asyncio
from pathlib import Path

# iPhone frame screen area coordinates (where content goes)
# Based on analysis: bezel is x=57-99 left, x=1420-1463 right
# Screen area is between the bezels with rounded corners
FRAME_SCREEN_X = 100  # Left bezel ends at ~99
FRAME_SCREEN_Y = 100  # Top bezel similar thickness
FRAME_SCREEN_WIDTH = 1320  # Centered: 1520 - 100*2 = 1320
FRAME_SCREEN_HEIGHT = 2868  # 3068 - 100*2 = 2868

# Frame dimensions (original)
FRAME_WIDTH = 1520
FRAME_HEIGHT = 3068

# Scale factor (20% = fits in preview frame)
SCALE_FACTOR = 0.20

# Finger dimensions - finger points DOWN at phone from above
FINGER_WIDTH_RATIO = 0.25  # finger width as ratio of phone width
FINGER_OVERLAP = 50  # how much finger overlaps onto the phone (pixels after scaling)

# Output canvas size
_scaled_phone_width = int(FRAME_WIDTH * SCALE_FACTOR)
_scaled_phone_height = int(FRAME_HEIGHT * SCALE_FACTOR)
_finger_width = int(_scaled_phone_width * FINGER_WIDTH_RATIO)
_finger_height = int(_finger_width * 1.5)  # maintain 2:3 aspect ratio

# Canvas: finger at top pointing down, phone below
# Finger hangs down and overlaps the phone slightly
OUTPUT_WIDTH = _scaled_phone_width // 2 * 2
OUTPUT_HEIGHT = (_scaled_phone_height + _finger_height - FINGER_OVERLAP + 20) // 2 * 2

# Corner radius for screen recording (to match iPhone screen corners)
CORNER_RADIUS = 138  # 2.5x larger for better match


async def _run_ffmpeg(cmd: list[str]) -> None:
    """Run FFmpeg command asynchronously."""
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {stderr.decode()}")


class TelegramCTACompositor:
    """Composites screen recording into iPhone frame with pointing finger."""

    def __init__(
        self,
        screen_recording: Path,
        output_path: Path,
        show_finger: bool = True,
    ):
        """Initialize compositor.

        Args:
            screen_recording: Path to the screen recording video
            output_path: Path for the output composed video
            show_finger: Whether to show pointing finger animation
        """
        self.screen_recording = Path(screen_recording)
        self.output_path = Path(output_path)
        self.show_finger = show_finger

    def get_frame_path(self) -> Path:
        """Get path to iPhone frame asset."""
        project_root = Path(__file__).parent.parent.parent

        # Check multiple locations (source assets, built dist, assets folder)
        search_dirs = [
            project_root / "ad-generator" / "src" / "assets",
            project_root / "ad-generator" / "dist" / "assets",
            project_root / "assets",
        ]

        for search_dir in search_dirs:
            if not search_dir.exists():
                continue
            # Look for iphone-frame*.png (handles Vite hashed filenames)
            matches = list(search_dir.glob("iphone-frame*.png"))
            if matches:
                return matches[0]

        raise FileNotFoundError("iPhone frame asset not found")

    def get_finger_path(self) -> Path | None:
        """Get path to pointing finger asset."""
        project_root = Path(__file__).parent.parent.parent

        # Check for finger asset in various locations
        possible_paths = [
            project_root / "assets" / "pointing-finger.png",
            project_root / "assets" / "pointing-finger.gif",
            project_root / "assets" / "pointing-finger.webm",
            project_root / "ad-generator" / "src" / "assets" / "pointing-finger.png",
        ]

        for path in possible_paths:
            if path.exists():
                return path

        return None

    async def compose(self) -> Path:
        """Compose the CTA video.

        Workflow:
        1. Scale screen recording to fit inside iPhone frame with rounded corners
        2. Overlay iPhone frame on top
        3. Scale entire composition to 75%
        4. Add pointing finger below the frame

        Returns:
            Path to the composed video
        """
        frame_path = self.get_frame_path()
        finger_path = self.get_finger_path() if self.show_finger else None

        # Calculate scaled iPhone position (centered horizontally)
        # Ensure dimensions are even for libx264
        scaled_frame_width = int(FRAME_WIDTH * SCALE_FACTOR) // 2 * 2
        scaled_frame_height = int(FRAME_HEIGHT * SCALE_FACTOR) // 2 * 2
        frame_x = (OUTPUT_WIDTH - scaled_frame_width) // 2

        # Phone position: below the finger (finger at top, pointing down)
        phone_y = _finger_height - FINGER_OVERLAP

        # Finger position: at top, centered, pointing down at phone
        finger_y = 0

        # Build FFmpeg filter complex
        # Input 0: screen recording
        # Input 1: iPhone frame (with alpha)
        # Input 2: pointing finger (optional)

        # Scale recording to fit screen area, add rounded corners using format and geq
        # The rounded corners are achieved by making corners transparent
        screen_scale = f"scale={FRAME_SCREEN_WIDTH}:{FRAME_SCREEN_HEIGHT}"

        # Create rounded corners mask using drawbox with rounded corners
        # We'll use a workaround: scale, then apply format=rgba and use geq to mask corners
        rounded_filter = (
            f"{screen_scale},format=rgba,"
            f"geq="
            f"'r=r(X,Y)':"
            f"'g=g(X,Y)':"
            f"'b=b(X,Y)':"
            f"'a=if(gt(pow(min(X,W-X)-{CORNER_RADIUS},2)+pow(min(Y,H-Y)-{CORNER_RADIUS},2),pow({CORNER_RADIUS},2))*"
            f"lt(min(X,W-X),{CORNER_RADIUS})*lt(min(Y,H-Y),{CORNER_RADIUS}),0,alpha(X,Y))'"
        )

        if finger_path and finger_path.exists():
            # With pointing finger at TOP, pointing DOWN at the phone
            filter_complex = (
                # Step 1: Scale recording and add rounded corners
                f"[0:v]{rounded_filter}[rounded];"
                # Step 2: Create OPAQUE black canvas, place recording in screen area
                f"color=c=black:s={FRAME_WIDTH}x{FRAME_HEIGHT}:d=10,format=rgba[bg];"
                f"[bg][rounded]overlay={FRAME_SCREEN_X}:{FRAME_SCREEN_Y}:format=auto[with_screen];"
                # Step 3: Overlay iPhone frame (bezel covers edges, screen area is transparent)
                f"[with_screen][1:v]overlay=0:0:format=auto[with_frame];"
                # Step 4: Scale the whole iPhone composition
                f"[with_frame]scale={scaled_frame_width}:{scaled_frame_height}[scaled_phone];"
                # Step 5: Create output canvas
                f"color=c=black:s={OUTPUT_WIDTH}x{OUTPUT_HEIGHT}:d=10[canvas];"
                # Step 6: Place scaled phone on canvas (below finger area)
                f"[canvas][scaled_phone]overlay={frame_x}:{phone_y}:format=auto[phone_placed];"
                # Step 7: Scale finger and place at TOP, pointing down (overlaps onto phone)
                f"[2:v]scale={_finger_width}:-1[finger_scaled];"
                f"[phone_placed][finger_scaled]overlay=(W-w)/2:{finger_y}:format=auto[out]"
            )
            inputs = [
                "-i", str(self.screen_recording),
                "-i", str(frame_path),
                "-i", str(finger_path),
            ]
        else:
            # Without pointing finger - phone starts at top
            filter_complex = (
                f"[0:v]{rounded_filter}[rounded];"
                # OPAQUE black canvas - exterior of phone will be black
                f"color=c=black:s={FRAME_WIDTH}x{FRAME_HEIGHT}:d=10,format=rgba[bg];"
                f"[bg][rounded]overlay={FRAME_SCREEN_X}:{FRAME_SCREEN_Y}:format=auto[with_screen];"
                f"[with_screen][1:v]overlay=0:0:format=auto[with_frame];"
                f"[with_frame]scale={scaled_frame_width}:{scaled_frame_height}[scaled_phone];"
                f"color=c=black:s={scaled_frame_width}x{scaled_frame_height}:d=10[canvas];"
                f"[canvas][scaled_phone]overlay=0:0:format=auto[out]"
            )
            inputs = [
                "-i", str(self.screen_recording),
                "-i", str(frame_path),
            ]

        # Build full command
        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-t", "4",  # Limit to 4 seconds
            str(self.output_path),
        ]

        await _run_ffmpeg(cmd)
        return self.output_path
