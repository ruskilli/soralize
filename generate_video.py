#!/usr/bin/env python3
"""
generate_video.py — Multi-scene Sora 2 video generator for Azure AI Foundry.

Usage:
    python generate_video.py storyboard.md [--dry-run] [--duration 12] [--size 1280x720]
    python generate_video.py storyboard.md --scenes 3,7,11   # regenerate specific scenes
    python generate_video.py storyboard.md --concat          # concat all into final MP4

Each run saves clips as take1, take2, … so existing files are never overwritten.
When --concat is used, the latest take of every scene is used for the final video.

Environment variables (set in .env or shell):
    AZURE_OPENAI_API_KEY      API key for the Azure OpenAI resource
    AZURE_OPENAI_ENDPOINT     e.g. https://my-resource.openai.azure.com/openai/v1/
    SORA_DEPLOYMENT_NAME      Deployment name (default: sora-2)
    OUTPUT_DIR                Directory for downloaded clips (default: ./output)
"""

# ---------------------------------------------------------------------------
# Bootstrap: if dependencies are missing, re-exec under the local venv so
# the script works without manual `source .venv/bin/activate`.
# Must run before any third-party imports.
# ---------------------------------------------------------------------------
import sys
import os

def _bootstrap() -> None:
    try:
        import dotenv  # noqa: F401
        import openai  # noqa: F401
    except ImportError:
        _dir = os.path.dirname(os.path.abspath(__file__))
        venv_python = os.path.join(_dir, ".venv", "bin", "python3")
        if os.path.isfile(venv_python) and os.path.abspath(sys.executable) != os.path.abspath(venv_python):
            # Re-exec under the venv interpreter — replaces the current process.
            os.execv(venv_python, [venv_python] + sys.argv)
        # Venv not found: install into the current interpreter as a last resort.
        import subprocess
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-q", "openai>=1.30.0", "python-dotenv"],
        )

_bootstrap()

# ---------------------------------------------------------------------------
# Standard-library and third-party imports (after bootstrap guarantees them)
# ---------------------------------------------------------------------------
import argparse
import re
import time
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class VoiceProfile:
    """Voice characteristics for voice-over narration."""
    gender: Optional[str] = None    # female | male | neutral
    language: Optional[str] = None  # e.g. English, Norwegian
    style: Optional[str] = None     # e.g. warm and calm, energetic, authoritative
    accent: Optional[str] = None    # e.g. British, American, neutral

    def describe(self) -> str:
        """Render a natural-language voice direction string for use in prompts."""
        parts = []
        if self.gender:
            parts.append(self.gender)
        if self.accent:
            parts.append(self.accent + " accent")
        if self.language and self.language.lower() not in ("english",):
            parts.append(f"speaking {self.language}")
        if self.style:
            parts.append(self.style + " delivery")
        return ", ".join(parts) if parts else ""

    def is_empty(self) -> bool:
        return not any([self.gender, self.language, self.style, self.accent])


@dataclass
class Scene:
    index: int
    title: str
    character_name: str
    location_name: Optional[str]
    duration: int
    size: str
    action_text: str
    voiceover: Optional[str] = None         # spoken words heard over the clip
    background_sound: Optional[str] = None  # ambient sound, music, or silence
    voice_override: Optional[VoiceProfile] = None  # per-scene voice; falls back to storyboard default

    # Populated after parsing is complete
    composed_prompt: str = ""
    video_id: Optional[str] = None
    output_file: Optional[Path] = None
    status: str = "pending"  # pending | submitted | completed | failed
    error: Optional[str] = None


@dataclass
class Storyboard:
    title: str
    global_style: str
    voice: VoiceProfile = field(default_factory=VoiceProfile)
    roles: dict[str, str] = field(default_factory=dict)        # name → description
    locations: dict[str, str] = field(default_factory=dict)    # name → description
    scenes: list[Scene] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Markdown parser
# ---------------------------------------------------------------------------

def _slug(text: str) -> str:
    """Convert a string to a safe directory/file slug."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _parse_inline_key(lines: list[str], key: str, default: str) -> str:
    """Extract a value from lines like '- key: value'."""
    for line in lines:
        m = re.match(rf"^\s*-\s+{re.escape(key)}\s*:\s*(.+)$", line, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return default


def parse_storyboard(md_text: str, default_duration: int, default_size: str) -> Storyboard:
    """Parse the structured Markdown storyboard into a Storyboard object."""
    lines = md_text.splitlines()

    # --- Split into top-level sections by H1 / H2 ---
    sections: dict[str, list[str]] = {}  # heading → content lines
    current_heading: Optional[str] = None
    h1_title = ""
    h1_body_lines: list[str] = []
    in_h1_body = False

    for line in lines:
        h1 = re.match(r"^#\s+(.+)$", line)
        h2 = re.match(r"^##\s+(.+)$", line)

        if h1:
            h1_title = h1.group(1).strip()
            current_heading = None
            in_h1_body = True
            continue

        if h2:
            in_h1_body = False
            current_heading = h2.group(1).strip()
            sections[current_heading] = []
            continue

        if in_h1_body:
            h1_body_lines.append(line)
        elif current_heading is not None:
            sections[current_heading].append(line)

    global_style = " ".join(l.strip() for l in h1_body_lines if l.strip())

    if not h1_title:
        raise ValueError("Storyboard must start with a H1 heading (# Title).")
    if not global_style:
        raise ValueError("No global style description found beneath the H1 heading.")

    # --- Parse Roles ---
    roles: dict[str, str] = {}
    role_lines = sections.get("Roles", [])
    _collect_h3_sections(role_lines, roles)

    # --- Parse Scenery ---
    locations: dict[str, str] = {}
    scenery_lines = sections.get("Scenery", [])
    _collect_h3_sections(scenery_lines, locations)

    # --- Parse global Voice profile ---
    voice_lines = sections.get("Voice", [])
    global_voice = VoiceProfile(
        gender=_parse_inline_key(voice_lines, "gender", "") or None,
        language=_parse_inline_key(voice_lines, "language", "") or None,
        style=_parse_inline_key(voice_lines, "style", "") or None,
        accent=_parse_inline_key(voice_lines, "accent", "") or None,
    )

    # --- Parse Scenes ---
    scene_lines = sections.get("Scenes", [])
    raw_scenes = _split_h3_sections(scene_lines)
    scenes: list[Scene] = []

    for idx, (scene_title, s_lines) in enumerate(raw_scenes, start=1):
        character = _parse_inline_key(s_lines, "character", "")
        location = _parse_inline_key(s_lines, "location", "") or None
        duration_str = _parse_inline_key(s_lines, "duration", str(default_duration))
        size = _parse_inline_key(s_lines, "size", default_size)
        voiceover = _parse_inline_key(s_lines, "voiceover", "") or None
        background_sound = _parse_inline_key(s_lines, "background-sound", "") or None

        # Per-scene voice overrides (any key present → create an override profile)
        vo_gender   = _parse_inline_key(s_lines, "voiceover-gender", "") or None
        vo_language = _parse_inline_key(s_lines, "voiceover-language", "") or None
        vo_style    = _parse_inline_key(s_lines, "voiceover-style", "") or None
        vo_accent   = _parse_inline_key(s_lines, "voiceover-accent", "") or None
        voice_override = (
            VoiceProfile(gender=vo_gender, language=vo_language, style=vo_style, accent=vo_accent)
            if any([vo_gender, vo_language, vo_style, vo_accent])
            else None
        )

        try:
            duration = int(duration_str)
        except ValueError:
            raise ValueError(
                f"Scene '{scene_title}': duration '{duration_str}' is not a valid integer."
            )

        # Action text = non-key lines (strip the key lines)
        key_pattern = re.compile(
            r"^\s*-\s+(?:character|location|duration|size|voiceover|background-sound"
            r"|voiceover-gender|voiceover-language|voiceover-style|voiceover-accent)\s*:",
            re.IGNORECASE,
        )
        action_lines = [l for l in s_lines if not key_pattern.match(l)]
        action_text = " ".join(l.strip() for l in action_lines if l.strip())

        # Strip redundant "Scene N: " prefix so the heading and index don't duplicate.
        display_title = re.sub(r"^Scene\s+\d+\s*:\s*", "", scene_title, flags=re.IGNORECASE).strip()

        scenes.append(Scene(
            index=idx,
            title=display_title,
            character_name=character,
            location_name=location,
            duration=duration,
            size=size,
            action_text=action_text,
            voiceover=voiceover,
            background_sound=background_sound,
            voice_override=voice_override,
        ))

    return Storyboard(
        title=h1_title,
        global_style=global_style,
        voice=global_voice,
        roles=roles,
        locations=locations,
        scenes=scenes,
    )


def _collect_h3_sections(lines: list[str], target: dict[str, str]) -> None:
    """Fill `target` with H3 heading → body text from `lines`."""
    for heading, body_lines in _split_h3_sections(lines):
        body = " ".join(l.strip() for l in body_lines if l.strip())
        target[heading] = body


def _split_h3_sections(lines: list[str]) -> list[tuple[str, list[str]]]:
    """Return list of (heading, content_lines) for each H3 block in `lines`."""
    result: list[tuple[str, list[str]]] = []
    current: Optional[str] = None
    buf: list[str] = []

    for line in lines:
        h3 = re.match(r"^###\s+(.+)$", line)
        if h3:
            if current is not None:
                result.append((current, buf))
            current = h3.group(1).strip()
            buf = []
        elif current is not None:
            buf.append(line)

    if current is not None:
        result.append((current, buf))

    return result


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate(storyboard: Storyboard) -> list[str]:
    """Return a list of validation error messages (empty = OK)."""
    errors: list[str] = []

    if not storyboard.roles:
        errors.append("No roles defined under ## Roles.")
    if not storyboard.scenes:
        errors.append("No scenes defined under ## Scenes.")

    for scene in storyboard.scenes:
        prefix = f"Scene {scene.index} '{scene.title}'"

        if not scene.character_name:
            errors.append(f"{prefix}: missing '- character:' key.")
        elif scene.character_name not in storyboard.roles:
            known = ", ".join(storyboard.roles.keys()) or "(none)"
            errors.append(
                f"{prefix}: character '{scene.character_name}' not found in Roles. "
                f"Known: {known}"
            )

        if scene.location_name and scene.location_name not in storyboard.locations:
            known = ", ".join(storyboard.locations.keys()) or "(none)"
            errors.append(
                f"{prefix}: location '{scene.location_name}' not found in Scenery. "
                f"Known: {known}"
            )

        if not (1 <= scene.duration <= 12) or scene.duration not in (4, 8, 12):
            errors.append(
                f"{prefix}: duration {scene.duration}s is not supported. "
                f"Valid values: 4, 8, 12."
            )

        valid_sizes = {
            "720x1280",   # portrait
            "1280x720",   # landscape (best for this project)
        }
        if scene.size not in valid_sizes:
            errors.append(
                f"{prefix}: size '{scene.size}' is not supported. "
                f"Valid: {', '.join(sorted(valid_sizes))}"
            )

        if not scene.action_text:
            errors.append(f"{prefix}: no action description text found.")

    return errors


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def compose_prompts(storyboard: Storyboard) -> None:
    """Populate scene.composed_prompt for every scene in-place."""
    for scene in storyboard.scenes:
        char_desc = storyboard.roles.get(scene.character_name, "")
        loc_desc = storyboard.locations.get(scene.location_name, "") if scene.location_name else ""

        parts = [storyboard.global_style.rstrip(".")]
        parts.append(f"Character: {scene.character_name} — {char_desc}".rstrip(" —"))
        if loc_desc:
            parts.append(f"Setting: {scene.location_name} — {loc_desc}".rstrip(" —"))
        parts.append(f"Scene: {scene.action_text}")
        if scene.voiceover:
            # Resolve effective voice profile: per-scene override wins, else global
            effective_voice = scene.voice_override or storyboard.voice
            voice_desc = effective_voice.describe() if not effective_voice.is_empty() else ""
            vo_line = f'Voice-over narration: "{scene.voiceover}"'
            if voice_desc:
                vo_line += f" ({voice_desc})"
            parts.append(vo_line)
        if scene.background_sound:
            parts.append(f"Audio: {scene.background_sound}")

        scene.composed_prompt = ". ".join(parts)


# ---------------------------------------------------------------------------
# Video generation
# ---------------------------------------------------------------------------

MAX_CONCURRENT_JOBS = 2
POLL_INTERVAL_SECONDS = 20


def generate_all(
    storyboard: Storyboard,
    client: OpenAI,
    deployment: str,
    output_dir: Path,
    scenes_to_generate: Optional[list[Scene]] = None,
) -> None:
    """Submit, poll, and download scenes, honouring the 2-job concurrency limit.

    Pass ``scenes_to_generate`` to regenerate a specific subset; defaults to all scenes.
    """
    semaphore = threading.Semaphore(MAX_CONCURRENT_JOBS)
    threads: list[threading.Thread] = []

    output_dir.mkdir(parents=True, exist_ok=True)

    target = scenes_to_generate if scenes_to_generate is not None else storyboard.scenes

    for scene in target:
        # Block here until a slot is free
        semaphore.acquire()
        t = threading.Thread(
            target=_process_scene,
            args=(scene, client, deployment, output_dir, semaphore),
            daemon=True,
        )
        threads.append(t)
        t.start()

    for t in threads:
        t.join()


def _process_scene(
    scene: Scene,
    client: OpenAI,
    deployment: str,
    output_dir: Path,
    semaphore: threading.Semaphore,
) -> None:
    """Submit a single scene job, poll until complete, and download the result."""
    try:
        print(f"[Scene {scene.index}] Submitting: {scene.title!r} ({scene.duration}s, {scene.size})")
        video = client.videos.create(
            model=deployment,
            prompt=scene.composed_prompt,
            seconds=scene.duration,
            size=scene.size,
        )
        scene.video_id = video.id
        scene.status = "submitted"
        print(f"[Scene {scene.index}] Job ID: {video.id} | Status: {video.status}")

        # Poll until terminal state
        while video.status not in ("completed", "failed", "cancelled"):
            print(
                f"[Scene {scene.index}] Status: {video.status} — "
                f"waiting {POLL_INTERVAL_SECONDS}s…"
            )
            time.sleep(POLL_INTERVAL_SECONDS)
            video = client.videos.retrieve(video.id)

        if video.status != "completed":
            scene.status = "failed"
            scene.error = f"Terminal status: {video.status}"
            print(f"[Scene {scene.index}] FAILED: {scene.error}")
            return

        # Download — save as a new alt take so existing clips are never overwritten
        take = _next_take_number(output_dir, scene)
        filename = f"scene_{scene.index:02d}_{_slug(scene.title)}_take{take}.mp4"
        out_path = output_dir / filename
        content = client.videos.download_content(video.id, variant="video")
        content.write_to_file(str(out_path))
        scene.output_file = out_path
        scene.status = "completed"
        print(f"[Scene {scene.index}] Downloaded → {out_path} (take {take})")

    except Exception as exc:
        scene.status = "failed"
        scene.error = str(exc)
        print(f"[Scene {scene.index}] ERROR: {exc}", file=sys.stderr)

    finally:
        semaphore.release()


# ---------------------------------------------------------------------------
# Alt-take helpers
# ---------------------------------------------------------------------------

def _next_take_number(output_dir: Path, scene: "Scene") -> int:
    """Return the next available take number for this scene (1-based)."""
    pattern = re.compile(
        rf"^scene_{scene.index:02d}_{re.escape(_slug(scene.title))}_take(\d+)\.mp4$"
    )
    taken: list[int] = []
    if output_dir.is_dir():
        for f in output_dir.iterdir():
            m = pattern.match(f.name)
            if m:
                taken.append(int(m.group(1)))
    return (max(taken) + 1) if taken else 1


def _latest_take_path(output_dir: Path, scene: "Scene") -> Optional[Path]:
    """Return the path to the highest-numbered existing take for a scene, or None."""
    pattern = re.compile(
        rf"^scene_{scene.index:02d}_{re.escape(_slug(scene.title))}_take(\d+)\.mp4$"
    )
    best_take = 0
    best_path: Optional[Path] = None
    if output_dir.is_dir():
        for f in output_dir.iterdir():
            m = pattern.match(f.name)
            if m:
                take_num = int(m.group(1))
                if take_num > best_take:
                    best_take = take_num
                    best_path = f
    return best_path


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_report(storyboard: Storyboard) -> None:
    col = [6, 30, 10, 8, 50]
    header = (
        f"{'Scene':<{col[0]}}  "
        f"{'Title':<{col[1]}}  "
        f"{'Status':<{col[2]}}  "
        f"{'Duration':<{col[3]}}  "
        f"{'Output':<{col[4]}}"
    )
    separator = "-" * len(header)
    print(f"\n{separator}")
    print(header)
    print(separator)
    for scene in storyboard.scenes:
        output = str(scene.output_file) if scene.output_file else (scene.error or "—")
        print(
            f"{scene.index:<{col[0]}}  "
            f"{scene.title[:col[1]]:<{col[1]}}  "
            f"{scene.status:<{col[2]}}  "
            f"{scene.duration}s{'':<{col[3] - len(str(scene.duration)) - 1}}  "
            f"{output[:col[4]]}"
        )
    print(separator)

    completed = sum(1 for s in storyboard.scenes if s.status == "completed")
    failed = sum(1 for s in storyboard.scenes if s.status == "failed")
    print(f"\n{completed} completed, {failed} failed out of {len(storyboard.scenes)} scenes.\n")


# ---------------------------------------------------------------------------
# Concatenation
# ---------------------------------------------------------------------------

def _ensure_ffmpeg() -> str:
    """Return the path to ffmpeg, installing it via Homebrew if not found."""
    import shutil
    import subprocess
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    brew = shutil.which("brew")
    if not brew:
        print(
            "Error: ffmpeg is not installed and Homebrew was not found.\n"
            "Install ffmpeg manually: https://ffmpeg.org/download.html",
            file=sys.stderr,
        )
        sys.exit(1)
    print("ffmpeg not found — installing via Homebrew (this may take a minute)…")
    subprocess.check_call([brew, "install", "ffmpeg"])
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("Error: ffmpeg install appeared to succeed but binary not found.", file=sys.stderr)
        sys.exit(1)
    return ffmpeg


def concat_clips(storyboard: Storyboard, output_dir: Path) -> None:
    """Concatenate all completed scene clips into a single final MP4 using ffmpeg.

    For each scene, the clip generated in this run takes priority; if the scene
    was not generated this run (e.g. when using --scenes), the latest existing
    take on disk is used instead.
    """
    import subprocess
    import tempfile

    clips: list[Path] = []
    for scene in sorted(storyboard.scenes, key=lambda s: s.index):
        if scene.status == "completed" and scene.output_file:
            # Just generated this run
            clips.append(scene.output_file)
        else:
            # Not generated this run — find the latest existing take on disk
            path = _latest_take_path(output_dir, scene)
            if path:
                clips.append(path)
            else:
                print(f"[Concat] Scene {scene.index} '{scene.title}': no clip found — skipping.")

    if not clips:
        print("No completed clips to concatenate.", file=sys.stderr)
        return

    if len(clips) == 1:
        print(f"Only one clip available — skipping concat, output is: {clips[0]}")
        return

    ffmpeg = _ensure_ffmpeg()

    # Write ffmpeg concat list to a temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        for clip in clips:
            # ffmpeg concat demuxer requires absolute paths or paths relative to the list file
            f.write(f"file '{clip.resolve()}'\n")
        concat_list = f.name

    final_path = output_dir / f"{_slug(storyboard.title)}_final.mp4"

    print(f"\nConcatenating {len(clips)} clips → {final_path}")
    try:
        subprocess.check_call(
            [
                ffmpeg,
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_list,
                "-c", "copy",
                str(final_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"Final video saved → {final_path}")
    finally:
        os.unlink(concat_list)


# ---------------------------------------------------------------------------
# Dry-run output
# ---------------------------------------------------------------------------

def print_dry_run(storyboard: Storyboard, scenes: Optional[list[Scene]] = None) -> None:
    target = scenes if scenes is not None else storyboard.scenes
    print(f"\n=== DRY RUN: {storyboard.title} ===")
    print(f"Global style: {storyboard.global_style}\n")
    if not storyboard.voice.is_empty():
        print(f"Voice profile: {storyboard.voice.describe()}")
    print(f"Roles:    {', '.join(storyboard.roles.keys())}")
    print(f"Scenery:  {', '.join(storyboard.locations.keys())}")
    if scenes is not None:
        print(f"Scenes:   {len(target)} of {len(storyboard.scenes)} (selected)\n")
    else:
        print(f"Scenes:   {len(target)}\n")

    for scene in target:
        print(f"--- Scene {scene.index}: {scene.title} ---")
        print(f"  Duration : {scene.duration}s")
        print(f"  Size     : {scene.size}")
        if scene.voiceover:
            effective_voice = scene.voice_override or storyboard.voice
            voice_desc = effective_voice.describe() if not effective_voice.is_empty() else ""
            print(f"  Voiceover: {scene.voiceover}")
            if voice_desc:
                src = "(scene override)" if scene.voice_override else "(global default)"
                print(f"  Voice    : {voice_desc} {src}")
        if scene.background_sound:
            print(f"  Audio    : {scene.background_sound}")
        print(f"  Prompt   : {scene.composed_prompt}")
        print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Generate a multi-scene video using Azure AI Foundry Sora 2."
    )
    parser.add_argument("storyboard", help="Path to the Markdown storyboard file.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and print composed prompts without making any API calls.",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=12,
        help="Default clip duration in seconds (1–20). Per-scene values in the MD override this.",
    )
    parser.add_argument(
        "--size",
        default="1280x720",
        help="Default output resolution. Supported: 1280x720 (landscape) or 720x1280 (portrait). Per-scene values override this.",
    )
    parser.add_argument(
        "--concat",
        action="store_true",
        help="After generation, concatenate all completed clips into a single final MP4 using ffmpeg.",
    )
    parser.add_argument(
        "--scenes",
        default=None,
        metavar="N[,N…]",
        help=(
            "Comma-separated scene numbers to regenerate, e.g. --scenes 3,7,11. "
            "Omit to generate all scenes. Every run saves a new alt take so no "
            "existing clip is ever overwritten."
        ),
    )
    args = parser.parse_args()

    # --- Load storyboard ---
    # For retakes (--scenes), prefer the copy already saved in the output dir so
    # the prompts are identical to the original run.  Fall back to the given path
    # if no output-dir copy exists yet (first run).
    md_path = Path(args.storyboard)
    if not md_path.is_file():
        print(f"Error: file not found: {md_path}", file=sys.stderr)
        sys.exit(1)

    # Peek at the title to build the output dir path, then check for an existing copy.
    _peek_text = md_path.read_text(encoding="utf-8")
    _peek_title_m = re.match(r"^#\s+(.+)$", _peek_text, re.MULTILINE)
    if _peek_title_m:
        _candidate = (
            Path(os.environ.get("OUTPUT_DIR", "./output"))
            / _slug(_peek_title_m.group(1).strip())
            / md_path.name
        )
        if args.scenes and _candidate.is_file():
            md_path = _candidate
            print(f"Using saved storyboard from output dir: {md_path}")

    md_text = md_path.read_text(encoding="utf-8")

    try:
        storyboard = parse_storyboard(md_text, args.duration, args.size)
    except ValueError as exc:
        print(f"Parse error: {exc}", file=sys.stderr)
        sys.exit(1)

    # --- Validate ---
    errors = validate(storyboard)
    if errors:
        print("Validation errors found:", file=sys.stderr)
        for err in errors:
            print(f"  • {err}", file=sys.stderr)
        sys.exit(1)

    # --- Compose prompts ---
    compose_prompts(storyboard)

    # --- Resolve selected scenes ---
    selected_scenes: list[Scene] = storyboard.scenes
    if args.scenes:
        try:
            scene_nums = {int(n.strip()) for n in args.scenes.split(",")}
        except ValueError:
            print(
                "Error: --scenes must be comma-separated integers, e.g. --scenes 2,5,9",
                file=sys.stderr,
            )
            sys.exit(1)
        invalid = scene_nums - {s.index for s in storyboard.scenes}
        if invalid:
            print(
                f"Error: scene number(s) not found in storyboard: {sorted(invalid)}",
                file=sys.stderr,
            )
            sys.exit(1)
        selected_scenes = [s for s in storyboard.scenes if s.index in scene_nums]

    # --- Dry run ---
    if args.dry_run:
        print_dry_run(storyboard, scenes=selected_scenes if args.scenes else None)
        sys.exit(0)

    # --- Resolve config ---
    api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
    deployment = os.environ.get("SORA_DEPLOYMENT_NAME", "sora-2")
    output_dir = Path(os.environ.get("OUTPUT_DIR", "./output")) / _slug(storyboard.title)

    if not api_key:
        print("Error: AZURE_OPENAI_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)
    if not endpoint:
        print("Error: AZURE_OPENAI_ENDPOINT is not set.", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(base_url=endpoint, api_key=api_key)

    print(f"\nProject  : {storyboard.title}")
    if args.scenes:
        nums_str = ", ".join(str(s.index) for s in selected_scenes)
        print(f"Scenes   : regenerating {len(selected_scenes)} of {len(storyboard.scenes)} ({nums_str})")
    else:
        print(f"Scenes   : {len(storyboard.scenes)}")
    print(f"Model    : {deployment}")
    print(f"Output   : {output_dir}\n")

    # --- Copy storyboard into output dir for version tracking (first run only) ---
    output_dir.mkdir(parents=True, exist_ok=True)
    storyboard_copy = output_dir / Path(args.storyboard).name
    if md_path.resolve() != storyboard_copy.resolve():
        import shutil
        shutil.copy2(md_path, storyboard_copy)
        print(f"Storyboard saved → {storyboard_copy}\n")
    else:
        print(f"Using storyboard → {storyboard_copy}\n")

    # --- Generate ---
    generate_all(storyboard, client, deployment, output_dir, scenes_to_generate=selected_scenes)

    # --- Report ---
    print_report(storyboard)

    # --- Concatenate ---
    if args.concat:
        concat_clips(storyboard, output_dir)


if __name__ == "__main__":
    main()
