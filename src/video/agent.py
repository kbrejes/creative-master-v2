"""
Technical Director Agent - Orchestrates asset gathering, generation, and composition.

This is the main agent class that coordinates:
- Brief parsing
- Tool selection
- Asset gathering (stock)
- Asset generation (AI)
- Video composition
- Output validation
"""

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any, Protocol

from .asset_gatherer import AssetGatherer
from .asset_generator import AssetGenerator
from .brief_parser import BriefParser
from .character_library import CharacterLibrary, ensure_character_image
from .compositor import Compositor
from .font_manager import ensure_font, get_font_for_locale
from .music_library import MusicLibrary, select_track
from .output_validator import OutputValidator
from .platform_specs import get_platform_format
from .providers import get_provider
from .schemas import (
    LANGUAGE_LOCALE_MAP,
    AssetRequirement,
    ToolHealth,
    VisualType,
)
from .subtitle_generator import SubtitleSegment, generate_from_shots, to_srt
from .tool_selector import ToolSelector
from .tts_preprocessor import prepare_for_tts
from .voice_catalog import Gender, select_voice
from .workflows import WorkflowConfig, get_workflow


class StockAPIProtocol(Protocol):
    """Protocol for stock API clients."""

    async def search(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        ...

    async def download(self, asset_id: str, output_path: str, **kwargs: Any) -> str:
        ...


class TTSAPIProtocol(Protocol):
    """Protocol for TTS API clients."""

    async def synthesize(
        self, text: str, voice_id: str = "", **kwargs: Any
    ) -> dict[str, Any]:
        ...


logger = logging.getLogger(__name__)


class TechnicalDirectorAgent:
    """
    Orchestrates the technical rendering of creative briefs.

    Workflow:
    1. Parse brief to extract requirements
    2. Select tools for each asset type
    3. Gather/generate assets in parallel
    4. Compose video timeline
    5. Validate output
    6. Return render result
    """

    def __init__(
        self,
        stock_api: StockAPIProtocol | None = None,
        tts_api: TTSAPIProtocol | None = None,
        output_dir: str = "/tmp/creative_master/renders",
        openai_api_key: str | None = None,
        elevenlabs_api_key: str | None = None,
        pexels_api_key: str | None = None,
        hedra_api_key: str | None = None,
        replicate_api_key: str | None = None,
    ):
        """
        Initialize Technical Director.

        Args:
            stock_api: Custom stock API client (for testing)
            tts_api: Custom TTS API client (for testing)
            output_dir: Directory for output files
            openai_api_key: OpenAI API key for DALL-E
            elevenlabs_api_key: ElevenLabs API key for TTS
            pexels_api_key: Pexels API key for stock video
            hedra_api_key: Hedra API key for UGC talking heads
            replicate_api_key: Replicate API key for SadTalker
        """
        self._hedra_api_key = hedra_api_key or ""
        self._replicate_api_key = replicate_api_key or ""
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Initialize components
        self.brief_parser = BriefParser()
        self.tool_selector = ToolSelector()
        self.asset_gatherer = AssetGatherer(
            stock_api=stock_api,
            pexels_api_key=pexels_api_key,
        )
        self.asset_generator = AssetGenerator(
            tts_api=tts_api,
            openai_api_key=openai_api_key,
            elevenlabs_api_key=elevenlabs_api_key,
        )
        self.compositor = Compositor(output_dir=str(self.output_dir))
        self.validator = OutputValidator()

        # Track fallbacks and warnings
        self._fallbacks_used: list[dict[str, Any]] = []
        self._total_cost: float = 0.0
        self._warnings: list[str] = []

    async def run(
        self,
        brief: dict[str, Any],
        budget_limit: float | None = None,
        workflow: WorkflowConfig | None = None,
    ) -> dict[str, Any]:
        """
        Render a creative brief to video.

        Args:
            brief: Creative brief with shot list
            budget_limit: Maximum budget for this render
            workflow: Pipeline preset config (defaults to Workflow 0)

        Returns:
            Render result with output files and logs
        """
        if workflow is None:
            workflow = get_workflow(0)

        self._fallbacks_used = []
        self._total_cost = 0.0
        self._warnings = []
        self._locale = LANGUAGE_LOCALE_MAP.get(workflow.language, "en-US")

        # Init UGC provider if workflow enables it
        self._ugc_provider = None
        self._character_library = None
        if workflow.ugc_enabled:
            api_key = (
                self._hedra_api_key
                if workflow.ugc_provider == "hedra"
                else self._replicate_api_key
            )
            self._ugc_provider = get_provider(
                workflow.ugc_provider, api_key=api_key,
            )
            self._character_library = CharacterLibrary.load_defaults()

        # Use a temp directory for all intermediate files
        work_dir = tempfile.mkdtemp(prefix="cm_work_")
        work_path = Path(work_dir)
        # Point compositor to temp work dir for intermediate outputs
        original_compositor_dir = self.compositor.output_dir
        self.compositor.output_dir = work_path

        try:
            # 1. Parse brief
            requirements = self.brief_parser.extract_requirements(brief)
            cost_estimate = self.brief_parser.estimate_cost(brief)

            # Check budget
            if budget_limit and cost_estimate.total_cost > budget_limit:
                return {
                    "status": "error",
                    "error": f"Estimated cost ${cost_estimate.total_cost:.2f} exceeds budget ${budget_limit:.2f}",
                }

            # 2. Determine target platform dimensions for clip normalization
            specs = brief.get("specifications", {})
            platforms = specs.get("platforms", [])
            target_platform = platforms[0] if platforms else None
            target_width, target_height = 1080, 1920
            if target_platform:
                fmt = get_platform_format(target_platform)
                target_width, target_height = fmt.width, fmt.height

            # 2b. Lock one voice for the entire video
            locale = LANGUAGE_LOCALE_MAP.get(workflow.language, "en-US")
            if workflow.voice_name:
                voice_edge_name = workflow.voice_name
            else:
                tone = workflow.voice_tone or self._get_primary_tone(brief.get("shot_list", []))
                gender = Gender(workflow.voice_gender) if workflow.voice_gender else None
                voice_profile = select_voice(tone, gender, locale=locale)
                voice_edge_name = voice_profile.edge_tts_name
            for req in requirements:
                if req.has_voiceover:
                    req.voiceover_config["voice"] = voice_edge_name

            # 3. Gather/generate assets for each shot
            shots_with_assets = await self._process_shots(
                requirements, budget_limit,
                target_width=target_width, target_height=target_height,
                workflow=workflow,
            )

            # 3b. Generate UGC overlay track (PIP avatar) if enabled
            avatar_video_path: str | None = None
            if workflow.ugc_overlay and self._ugc_provider is not None:
                avatar_video_path = await self._generate_ugc_overlay_track(
                    shots_with_assets, work_path, workflow,
                )

            # 4. Compose video
            brief_id = brief.get("brief_id", "unknown")
            output_path = str(work_path / f"{brief_id}.mp4")
            composition_result = await self._compose_video(shots_with_assets, output_path)

            if "error" in composition_result:
                return {
                    "status": "error",
                    "error": composition_result["error"],
                    "composition_log": self._build_composition_log(shots_with_assets),
                }

            # 4b. Probe actual VO durations for audio/subtitle sync
            current_video = output_path
            shot_list = brief.get("shot_list", [])
            vo_durations = await self._probe_vo_durations(shots_with_assets)

            # 5. Merge voiceover audio into video
            audio_tracks = self._collect_audio_tracks(
                shots_with_assets, shot_list, vo_durations or None,
                workflow=workflow,
            )

            # 5a. Extend video if VO extends past composed duration
            #     Re-trim last clip longer from original footage → re-compose
            total_duration = specs.get("total_duration", 0)
            if audio_tracks and vo_durations:
                last_track = audio_tracks[-1]
                last_shot_num = last_track["shot_number"]
                last_vo_dur = vo_durations.get(last_shot_num, 0.0)
                last_vo_end = last_track["start_time"] + last_vo_dur
                if last_vo_end > total_duration:
                    extra_needed = last_vo_end - total_duration
                    last_shot = next(
                        (s for s in shots_with_assets
                         if s["shot_number"] == last_shot_num),
                        None,
                    )
                    original_clip = (
                        last_shot.get("assets", {})
                        .get("visual", {})
                        .get("path", "")
                        if last_shot else ""
                    )
                    last_brief_dur = next(
                        (s["duration_seconds"] for s in shot_list
                         if s["shot_number"] == last_shot_num),
                        0.0,
                    )
                    if original_clip and last_shot:
                        ext_path = str(
                            work_path / f"extended_shot_{last_shot_num}.mp4"
                        )
                        needed_dur = last_brief_dur + extra_needed
                        trim_result = await self.compositor.trim_clip(
                            input_path=original_clip,
                            output_path=ext_path,
                            duration=needed_dur,
                            target_width=target_width,
                            target_height=target_height,
                        )
                        # Fall back to loop if trim fails (source too short)
                        if not trim_result.get("success"):
                            loop_path = str(
                                work_path / f"looped_shot_{last_shot_num}.mp4"
                            )
                            trim_result = await self.compositor.loop_extend_clip(
                                input_path=original_clip,
                                output_path=loop_path,
                                target_duration=needed_dur,
                                target_width=target_width,
                                target_height=target_height,
                            )
                            if trim_result.get("success"):
                                ext_path = loop_path
                        if trim_result.get("success"):
                            last_shot["video_path"] = ext_path
                            current_video = str(
                                work_path / f"{brief_id}_extended.mp4"
                            )
                            await self._compose_video(
                                shots_with_assets, current_video
                            )

            if audio_tracks:
                audio_output = str(work_path / f"{brief_id}_audio.mp4")
                audio_result = await self.compositor.overlay_audio_tracks(
                    video_path=current_video,
                    audio_tracks=audio_tracks,
                    output_path=audio_output,
                )
                if audio_result.get("success"):
                    current_video = audio_output

            # 5b. Add background music with sidechain ducking
            music_mood = workflow.music_mood or self._get_music_mood(shot_list)
            track = select_track(music_mood, min_duration=int(total_duration))
            if track:
                music_lib = MusicLibrary()
                music_path = await music_lib.download_track(
                    track, str(work_path)
                )
                if music_path:
                    music_output = str(work_path / f"{brief_id}_music.mp4")
                    music_result = await self.compositor.add_background_music(
                        video_path=current_video,
                        music_path=music_path,
                        output_path=music_output,
                        music_volume=workflow.music_volume,
                    )
                    if music_result.get("success"):
                        current_video = music_output

            # 6. Platform export (scale to target resolution before subtitles)
            if target_platform:
                platform_output = str(work_path / f"{brief_id}_platform.mp4")
                await self.compositor.export_for_platform(
                    input_path=current_video,
                    output_path=platform_output,
                    platform=target_platform,
                )
                current_video = platform_output

            # 7. Generate subtitles from voiceover texts (synced to actual audio)
            audio_start_times = {
                t["shot_number"]: t["start_time"]
                for t in audio_tracks
            } if audio_tracks else None
            srt_path, subtitle_segments = await self._generate_subtitles(
                shot_list, total_duration, str(work_path),
                vo_durations=vo_durations or None,
                audio_start_times=audio_start_times,
            )

            # 8. Download font and set on compositor (locale-aware for Cyrillic)
            effective_font = get_font_for_locale(workflow.font_name, self._locale)
            font_path = await ensure_font(font_name=effective_font)
            self.compositor.font_path = font_path

            # 9. Burn subtitles using Pillow overlay with SubtitleConfig
            if subtitle_segments:
                subs_output = str(work_path / f"{brief_id}_subs.mp4")
                burn_result = await self.compositor.burn_subtitles_overlay(
                    input_path=current_video,
                    output_path=subs_output,
                    segments=subtitle_segments,
                    video_width=target_width,
                    video_height=target_height,
                    subtitle_config=workflow.subtitle_config,
                )
                if burn_result.get("success"):
                    current_video = subs_output

            # 9b. Overlay PIP avatar (after subtitles — avatar on top)
            if avatar_video_path and workflow.ugc_overlay:
                pip_output = str(work_path / f"{brief_id}_pip.mp4")
                pip_result = await self.compositor.overlay_pip_avatar(
                    video_path=current_video,
                    avatar_path=avatar_video_path,
                    output_path=pip_output,
                    video_width=target_width,
                    video_height=target_height,
                    overlay_size=workflow.ugc_overlay_size,
                    position=workflow.ugc_overlay_position,
                    margin=workflow.ugc_overlay_margin,
                    circle_crop=workflow.ugc_overlay_circle,
                )
                if pip_result.get("success"):
                    current_video = pip_output

            # 10. Copy final video to output dir with proper name
            platform_name = target_platform or "video"
            final_name = f"{brief_id}_{platform_name}_{target_width}x{target_height}.mp4"
            final_path = str(self.output_dir / final_name)
            shutil.copy2(current_video, final_path)
            current_video = final_path

            # Validate output
            render_output = self._build_render_output(
                brief, current_video, shots_with_assets,
                srt_path=srt_path,
                language=workflow.language,
            )
            validation = await self.validator.validate_all(render_output, brief)

            status = "warning" if not validation["passed"] or self._warnings else "success"

            result_dict: dict[str, Any] = {
                "status": status,
                "output_files": render_output.get("output_files", {}),
                "composition_log": self._build_composition_log(shots_with_assets),
                "validation": validation,
            }
            if self._warnings:
                result_dict["warnings"] = list(self._warnings)

            return result_dict

        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "composition_log": {
                    "fallbacks_used": bool(self._fallbacks_used),
                    "total_cost": self._total_cost,
                },
            }
        finally:
            # Restore compositor output dir and clean up temp work dir
            self.compositor.output_dir = original_compositor_dir
            shutil.rmtree(work_dir, ignore_errors=True)

    async def _process_shots(
        self,
        requirements: list[AssetRequirement],
        budget_limit: float | None,
        target_width: int = 1080,
        target_height: int = 1920,
        workflow: WorkflowConfig | None = None,
    ) -> list[dict[str, Any]]:
        """
        Process all shots: gather or generate assets.

        Args:
            requirements: List of asset requirements
            budget_limit: Budget limit
            target_width: Target video width for clip normalization
            target_height: Target video height for clip normalization
            workflow: Pipeline preset config

        Returns:
            List of shots with asset paths
        """
        budget_remaining = budget_limit

        async def process_shot(req: AssetRequirement) -> dict[str, Any]:
            nonlocal budget_remaining

            # Route UGC shots to dedicated handler (skip in overlay mode —
            # overlay mode uses stock footage with PIP avatar on top)
            if (req.visual_type == VisualType.UGC_TALKING_HEAD
                    and self._ugc_provider is not None
                    and not (workflow and workflow.ugc_overlay)):
                return await self._process_ugc_shot(
                    req, budget_remaining,
                    target_width=target_width,
                    target_height=target_height,
                )

            shot_data: dict[str, Any] = {
                "shot_number": req.shot_number,
                "assets": {},
            }

            # Get visual asset
            visual_asset = await self._get_visual_asset(req, budget_remaining)
            if visual_asset:
                original_path = visual_asset.get("path", "")
                shot_data["assets"]["visual"] = visual_asset
                cost = visual_asset.get("cost", 0)
                self._total_cost += cost
                if budget_remaining:
                    budget_remaining -= cost

                # Trim clip to shot duration and normalize resolution
                if original_path and req.min_duration > 0:
                    trimmed_path = str(
                        self.compositor.output_dir / f"trimmed_shot_{req.shot_number}.mp4"
                    )
                    trim_result = await self.compositor.trim_clip(
                        input_path=original_path,
                        output_path=trimmed_path,
                        duration=req.min_duration,
                        target_width=target_width,
                        target_height=target_height,
                    )
                    if trim_result.get("success"):
                        shot_data["video_path"] = trim_result["output_path"]
                    else:
                        shot_data["video_path"] = original_path
                else:
                    shot_data["video_path"] = original_path

            # Get voiceover if needed
            if req.has_voiceover and req.voiceover_text:
                vo_asset = await self._get_voiceover(req, budget_remaining)
                if vo_asset:
                    shot_data["audio_path"] = vo_asset.get("path", "")
                    shot_data["assets"]["voiceover"] = vo_asset
                    cost = vo_asset.get("cost", 0)
                    self._total_cost += cost
                    if budget_remaining:
                        budget_remaining -= cost
                else:
                    shot_data["vo_failed"] = True
                    self._warnings.append(
                        f"Voiceover failed for shot {req.shot_number}"
                    )

            # Add text overlay info
            if req.has_text_overlay and req.text_overlay:
                shot_data["text_overlay"] = {
                    "text": req.text_overlay.text,
                    "position": req.text_overlay.position.value if hasattr(req.text_overlay.position, 'value') else req.text_overlay.position,
                    "start_time": req.text_overlay.start_time,
                    "duration": req.text_overlay.duration,
                }

            return shot_data

        # Process shots sequentially to avoid Edge TTS concurrency issues
        # (concurrent WebSocket connections can produce 0-byte files)
        results = []
        for req in requirements:
            results.append(await process_shot(req))
        return results

    async def _process_ugc_shot(
        self,
        req: AssetRequirement,
        budget_remaining: float | None,
        target_width: int = 1080,
        target_height: int = 1920,
    ) -> dict[str, Any]:
        """Process a UGC talking head shot.

        For UGC shots, VO must be generated FIRST because the talking head
        provider needs audio for lip-sync.

        Args:
            req: Asset requirement for this shot.
            budget_remaining: Remaining budget.
            target_width: Video width.
            target_height: Video height.

        Returns:
            Shot data dict with ugc_baked_audio=True flag.
        """
        shot_data: dict[str, Any] = {
            "shot_number": req.shot_number,
            "assets": {},
        }

        # Step 1: Generate VO audio FIRST (provider needs it for lip-sync)
        vo_asset = None
        if req.has_voiceover and req.voiceover_text:
            vo_asset = await self._get_voiceover(req, budget_remaining)
            if vo_asset:
                shot_data["audio_path"] = vo_asset.get("path", "")
                shot_data["assets"]["voiceover"] = vo_asset
                cost = vo_asset.get("cost", 0)
                self._total_cost += cost

        if not vo_asset or not vo_asset.get("path"):
            self._warnings.append(
                f"UGC shot {req.shot_number}: VO failed, falling back to stock"
            )
            req.visual_type = VisualType.STOCK
            return await self._get_stock_shot_data(req, budget_remaining,
                                                    target_width, target_height)

        # Step 2: Select character
        character = None
        if self._character_library:
            character = self._character_library.select_character()

        if not character:
            self._warnings.append(
                f"UGC shot {req.shot_number}: No character available, falling back to stock"
            )
            req.visual_type = VisualType.STOCK
            return await self._get_stock_shot_data(req, budget_remaining,
                                                    target_width, target_height)

        # Step 3: Ensure character image is cached locally
        try:
            image_path = await ensure_character_image(character)
        except Exception:
            self._warnings.append(
                f"UGC shot {req.shot_number}: Character image download failed, "
                "falling back to stock"
            )
            req.visual_type = VisualType.STOCK
            return await self._get_stock_shot_data(req, budget_remaining,
                                                    target_width, target_height)

        # Step 4: Generate talking head video
        audio_path = vo_asset["path"]
        output_path = str(
            self.compositor.output_dir / f"ugc_shot_{req.shot_number}.mp4"
        )

        try:
            result = await self._ugc_provider.generate(
                image_path, audio_path, output_path,
            )

            # Normalize UGC output to target resolution (e.g. SadTalker
            # outputs 256x256 — need to scale+pad to 1080x1920)
            video_path = result.video_path
            norm_path = str(
                self.compositor.output_dir / f"ugc_norm_{req.shot_number}.mp4"
            )
            trim_result = await self.compositor.trim_clip(
                input_path=result.video_path,
                output_path=norm_path,
                duration=req.min_duration,
                target_width=target_width,
                target_height=target_height,
            )
            if trim_result.get("success"):
                video_path = trim_result["output_path"]

            shot_data["video_path"] = video_path
            shot_data["assets"]["visual"] = {
                "path": video_path,
                "type": "ugc_talking_head",
                "tool": result.provider,
                "cost": result.cost,
            }
            # Mark that VO is baked into the video — skip audio overlay
            shot_data["ugc_baked_audio"] = True
            self._total_cost += result.cost
        except Exception as e:
            self._warnings.append(
                f"UGC shot {req.shot_number}: Provider failed ({e}), "
                "falling back to stock"
            )
            # Fall back to stock — reuse VO but get stock visual
            req.visual_type = VisualType.STOCK
            fallback = await self._get_stock_shot_data(
                req, budget_remaining, target_width, target_height,
            )
            # Keep the VO from UGC attempt
            fallback["audio_path"] = audio_path
            fallback["assets"]["voiceover"] = vo_asset
            return fallback

        return shot_data

    async def _generate_ugc_overlay_track(
        self,
        shots_with_assets: list[dict[str, Any]],
        work_path: Path,
        workflow: WorkflowConfig,
    ) -> str | None:
        """Generate a single avatar video track from all VO audio.

        1. Collect VO audio paths from processed shots.
        2. Concatenate into a single audio file.
        3. Select character and generate talking head video.

        Args:
            shots_with_assets: Processed shots with audio_path fields.
            work_path: Working directory for intermediate files.
            workflow: Pipeline preset config.

        Returns:
            Path to avatar video, or None if generation fails.
        """
        # Collect VO audio paths in shot order
        sorted_shots = sorted(
            shots_with_assets, key=lambda s: s.get("shot_number", 0),
        )
        vo_paths = [
            s["audio_path"] for s in sorted_shots if s.get("audio_path")
        ]
        if not vo_paths:
            self._warnings.append("UGC overlay: no VO audio to lip-sync")
            return None

        # Concatenate all VO into one audio file
        combined_audio = str(work_path / "combined_vo.m4a")
        concat_result = await self.compositor.concat_audio_files(
            vo_paths, combined_audio,
        )
        if not concat_result.get("success"):
            self._warnings.append("UGC overlay: audio concat failed")
            return None
        combined_audio = concat_result.get("output_path", combined_audio)

        # Select character
        character = None
        if self._character_library:
            character = self._character_library.select_character()
        if not character:
            self._warnings.append("UGC overlay: no character available")
            return None

        # Ensure character image
        try:
            image_path = await ensure_character_image(character)
        except Exception:
            self._warnings.append("UGC overlay: character image download failed")
            return None

        # Generate avatar video
        output_path = str(work_path / "ugc_overlay_avatar.mp4")
        try:
            result = await self._ugc_provider.generate(
                image_path, combined_audio, output_path,
            )
            self._total_cost += result.cost
            return result.video_path
        except Exception as e:
            self._warnings.append(
                f"UGC overlay: provider failed ({e})"
            )
            return None

    async def _get_stock_shot_data(
        self,
        req: AssetRequirement,
        budget_remaining: float | None,
        target_width: int,
        target_height: int,
    ) -> dict[str, Any]:
        """Get stock visual for a shot (used as UGC fallback)."""
        shot_data: dict[str, Any] = {
            "shot_number": req.shot_number,
            "assets": {},
        }
        visual_asset = await self._get_visual_asset(req, budget_remaining)
        if visual_asset:
            original_path = visual_asset.get("path", "")
            shot_data["assets"]["visual"] = visual_asset
            if original_path and req.min_duration > 0:
                trimmed_path = str(
                    self.compositor.output_dir / f"trimmed_shot_{req.shot_number}.mp4"
                )
                trim_result = await self.compositor.trim_clip(
                    input_path=original_path,
                    output_path=trimmed_path,
                    duration=req.min_duration,
                    target_width=target_width,
                    target_height=target_height,
                )
                if trim_result.get("success"):
                    shot_data["video_path"] = trim_result["output_path"]
                else:
                    shot_data["video_path"] = original_path
            else:
                shot_data["video_path"] = original_path
        return shot_data

    async def _get_visual_asset(
        self,
        requirement: AssetRequirement,
        budget_remaining: float | None,
    ) -> dict[str, Any] | None:
        """
        Get visual asset based on requirement type.

        Args:
            requirement: Asset requirement
            budget_remaining: Remaining budget

        Returns:
            Asset info or None
        """
        # Select appropriate tool
        tool = self.tool_selector.select_visual_tool(
            {"visual_type": requirement.visual_type.value},
            max_cost=budget_remaining,
        )

        try:
            if requirement.visual_type == VisualType.STOCK:
                result = await self.asset_gatherer.get_stock_video({
                    "search_terms": requirement.search_terms,
                    "min_duration": requirement.min_duration,
                })

                if result and not result.get("fallback_needed"):
                    return {
                        "path": result.get("path", ""),
                        "type": "stock_video",
                        "tool": tool["name"],
                        "cost": tool.get("cost", 0),
                    }

                # Try fallback
                return await self._use_fallback_stock(requirement)

            elif requirement.visual_type == VisualType.AI_GENERATED:
                prompt = requirement.generation_prompt or requirement.description
                result = await self.asset_generator.generate_image(prompt)

                if result and not result.get("error"):
                    return {
                        "path": result.get("path", ""),
                        "type": "ai_image",
                        "tool": tool["name"],
                        "cost": result.get("cost", 0),
                    }

            elif requirement.visual_type == VisualType.BRAND_ASSET:
                # Brand assets are local files - would be handled by asset manager
                return {
                    "path": "",  # Would come from brand asset library
                    "type": "brand_asset",
                    "tool": "local",
                    "cost": 0,
                }

            elif requirement.visual_type == VisualType.UGC_TALKING_HEAD:
                # UGC talking head — no providers yet, fall back to stock
                self._warnings.append(
                    f"UGC talking head not available for shot {requirement.shot_number}, "
                    "falling back to stock video"
                )
                # Re-use stock pipeline as fallback
                requirement.visual_type = VisualType.STOCK
                return await self._get_visual_asset(requirement, budget_remaining)

            elif requirement.visual_type == VisualType.SCREEN_RECORDING:
                # Screen recording would be handled by separate tool
                return {
                    "path": "",  # Would come from screen recorder
                    "type": "screen_recording",
                    "tool": "playwright",
                    "cost": 0,
                }

        except Exception as e:
            # Try fallback
            fallback_name = self.tool_selector.get_fallback(tool["name"])
            if fallback_name:
                self._fallbacks_used.append({
                    "original": tool["name"],
                    "fallback": fallback_name,
                    "reason": str(e),
                })
                # Would recursively try fallback tool here

        return None

    async def _use_fallback_stock(
        self,
        requirement: AssetRequirement,
    ) -> dict[str, Any] | None:
        """
        Try fallback stock sources.

        Args:
            requirement: Asset requirement

        Returns:
            Asset from fallback or None
        """
        # Mark that we used fallback
        self._fallbacks_used.append({
            "original": "pexels",
            "fallback": "storyblocks",
            "reason": "Primary source failed",
        })

        # In real implementation, would try storyblocks, pixabay, etc.
        # For now, return placeholder
        return [{"id": "fallback-placeholder"}]

    async def _get_voiceover(
        self,
        requirement: AssetRequirement,
        budget_remaining: float | None,
    ) -> dict[str, Any] | None:
        """
        Generate voiceover for a shot.

        Args:
            requirement: Asset requirement with voiceover text
            budget_remaining: Remaining budget

        Returns:
            Voiceover asset info or None
        """
        tool = self.tool_selector.select_audio_tool("tts", max_cost=budget_remaining)

        try:
            tts_text = prepare_for_tts(requirement.voiceover_text, locale=self._locale)
            result = await self.asset_generator.generate_voiceover(
                text=tts_text,
                voice_config=requirement.voiceover_config,
            )

            if result and not result.get("error"):
                return {
                    "path": result.get("path", ""),
                    "type": "voiceover",
                    "tool": tool["name"],
                    "cost": result.get("cost", 0),
                    "duration": result.get("duration_seconds", 0),
                }

        except Exception:
            logger.exception("Voiceover generation failed for shot %s", requirement.shot_number)

        return None

    async def _probe_vo_durations(
        self,
        shots_with_assets: list[dict[str, Any]],
    ) -> dict[int, float]:
        """
        Probe actual VO audio duration for each shot using ffprobe.

        Args:
            shots_with_assets: Processed shots with audio_path fields

        Returns:
            Map of shot_number -> actual VO duration in seconds
        """
        durations: dict[int, float] = {}
        for shot in shots_with_assets:
            audio_path = shot.get("audio_path", "")
            shot_num = shot.get("shot_number", 0)
            if audio_path and shot_num:
                try:
                    info = await self.compositor.get_video_info(audio_path)
                    dur = info.get("duration", 0.0)
                    if dur > 0:
                        durations[shot_num] = dur
                except Exception:
                    pass  # Fall back to brief duration
        return durations

    async def _generate_subtitles(
        self,
        shots: list[dict[str, Any]],
        total_duration: float,
        output_dir: str,
        vo_durations: dict[int, float] | None = None,
        audio_start_times: dict[int, float] | None = None,
    ) -> tuple[str | None, list[SubtitleSegment]]:
        """
        Generate SRT subtitle file from shot voiceover texts.

        Args:
            shots: Shot list with audio.voiceover.text fields
            total_duration: Total video duration in seconds
            output_dir: Directory to write the SRT file
            vo_durations: Map of shot_number -> actual VO duration
            audio_start_times: Map of shot_number -> actual VO start time

        Returns:
            Tuple of (SRT file path or None, list of SubtitleSegment)
        """
        segments = generate_from_shots(
            shots,
            vo_durations=vo_durations,
            audio_start_times=audio_start_times,
        )
        if not segments:
            return None, []

        srt_content = to_srt(segments)
        srt_path = Path(output_dir) / "subtitles.srt"
        srt_path.write_text(srt_content)
        return str(srt_path), segments

    # Small gap between consecutive VO phrases to prevent overlap (seconds)
    VO_GAP_SECONDS: float = 0.05

    def _collect_audio_tracks(
        self,
        shots: list[dict[str, Any]],
        shot_list: list[dict[str, Any]],
        vo_durations: dict[int, float] | None = None,
        workflow: WorkflowConfig | None = None,
    ) -> list[dict[str, Any]]:
        """
        Collect audio track info from processed shots.

        When vo_durations is provided, places each VO sequentially using
        actual audio duration + a small gap, ensuring no overlap.
        The start time is the later of (shot visual boundary, previous VO end + gap).

        Args:
            shots: Processed shots with audio_path fields
            shot_list: Brief's shot list with duration_seconds
            vo_durations: Map of shot_number -> actual VO audio duration in seconds
            workflow: Pipeline preset config for VO gap

        Returns:
            List of audio track dicts with path and start_time
        """
        vo_gap = workflow.vo_gap_seconds if workflow else self.VO_GAP_SECONDS

        # Build duration lookup from brief's shot list
        duration_by_shot = {
            s.get("shot_number", 0): s.get("duration_seconds", 0.0)
            for s in shot_list
        }

        sorted_shots = sorted(shots, key=lambda s: s.get("shot_number", 0))
        tracks = []
        shot_boundary = 0.0  # cumulative brief duration
        vo_end = 0.0  # when previous VO finishes

        for shot in sorted_shots:
            audio_path = shot.get("audio_path", "")
            shot_num = shot.get("shot_number", 0)
            shot_duration = duration_by_shot.get(shot_num, 0.0)

            # Skip shots where VO is baked into the video (UGC talking heads)
            if shot.get("ugc_baked_audio"):
                shot_boundary += shot_duration
                continue

            if audio_path:
                if vo_durations:
                    actual_dur = vo_durations.get(shot_num, shot_duration)
                    # Place VOs back-to-back with minimal gap for tight pacing
                    start = (vo_end + vo_gap) if vo_end > 0 else 0.0
                    tracks.append({
                        "path": audio_path,
                        "start_time": start,
                        "shot_number": shot_num,
                    })
                    vo_end = start + actual_dur
                else:
                    tracks.append({
                        "path": audio_path,
                        "start_time": shot_boundary,
                        "shot_number": shot_num,
                    })

            shot_boundary += shot_duration

        return tracks

    _TONE_TO_MOOD: dict[str, str] = {
        "conversational": "chill",
        "professional": "corporate",
        "energetic": "upbeat",
        "warm": "inspirational",
        "authoritative": "dramatic",
        "young": "upbeat",
    }

    @staticmethod
    def _get_primary_tone(shot_list: list[dict[str, Any]]) -> str:
        """Return the first voiceover tone found in the shot list."""
        for shot in shot_list:
            tone = (
                shot.get("audio", {})
                .get("voiceover", {})
                .get("tone", "")
            )
            if tone:
                return tone
        return "conversational"

    def _get_music_mood(self, shot_list: list[dict[str, Any]]) -> str:
        """Derive music mood from the brief's primary voiceover tone."""
        for shot in shot_list:
            tone = (
                shot.get("audio", {})
                .get("voiceover", {})
                .get("tone", "")
            )
            if tone:
                return self._TONE_TO_MOOD.get(tone, "chill")
        return "chill"

    async def _compose_video(
        self,
        shots: list[dict[str, Any]],
        output_path: str,
    ) -> dict[str, Any]:
        """
        Compose video from processed shots.

        Args:
            shots: List of shots with asset paths
            output_path: Output video path

        Returns:
            Composition result
        """
        return await self.compositor.compose(shots, output_path)

    def _build_render_output(
        self,
        brief: dict[str, Any],
        output_path: str,
        shots: list[dict[str, Any]],
        srt_path: str | None = None,
        language: str = "en",
    ) -> dict[str, Any]:
        """
        Build render output structure.

        Args:
            brief: Original brief
            output_path: Output video path
            shots: Processed shots
            srt_path: Path to subtitle file (if generated)

        Returns:
            Render output dict
        """
        specs = brief.get("specifications", {})

        output_files: dict[str, Any] = {
            "video": {
                "path": output_path,
                "duration_seconds": specs.get("total_duration", 0),
                "resolution": specs.get("resolution", "1080x1920"),
                "file_size_mb": 0,  # Would be calculated after export
            },
        }

        if srt_path:
            output_files["subtitles"] = {
                "path": srt_path,
                "language": language,
            }

        return {
            "render_id": f"render-{brief.get('brief_id', 'unknown')}",
            "brief_id": brief.get("brief_id", ""),
            "output_files": output_files,
            "composition_log": self._build_composition_log(shots),
        }

    def _build_composition_log(
        self,
        shots: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Build composition log for debugging and tracking.

        Args:
            shots: Processed shots

        Returns:
            Composition log dict
        """
        assets_used = []
        for shot in shots:
            shot_num = shot.get("shot_number", 0)
            for asset_type, asset_info in shot.get("assets", {}).items():
                if isinstance(asset_info, dict):
                    assets_used.append({
                        "shot": shot_num,
                        "type": asset_info.get("type", asset_type),
                        "tool": asset_info.get("tool", "unknown"),
                    })

        return {
            "shots_processed": len(shots),
            "shots_successful": sum(1 for s in shots if s.get("video_path") or s.get("assets")),
            "assets_used": assets_used,
            "fallbacks_used": bool(self._fallbacks_used),
            "fallback_details": self._fallbacks_used,
            "total_cost": self._total_cost,
        }

    def update_tool_health(self, tool_name: str, health: ToolHealth | str) -> None:
        """
        Update health status of a tool.

        Args:
            tool_name: Name of the tool
            health: New health status
        """
        self.tool_selector.set_tool_health(tool_name, health)

    async def close(self) -> None:
        """Clean up resources."""
        await self.asset_gatherer.close()
        await self.asset_generator.close()
