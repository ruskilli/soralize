# soralize

A Python tool that generates multi-scene videos from a Markdown storyboard using [Azure AI Foundry Sora 2](https://azure.microsoft.com/en-us/products/ai-services/openai-service). Each scene is submitted as a separate clip, all sharing the same global style prompt to keep the visual language consistent. Clips are saved as numbered alt takes so no generated file is ever overwritten.

---

## Requirements

- Python 3.10+
- An Azure AI Foundry resource with a `sora-2` deployment
- ffmpeg (only needed for `--concat`; auto-installed via Homebrew on macOS if missing)

---

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

The script also bootstraps itself automatically — if you run it without activating the venv it will re-exec under `.venv/bin/python3`.

---

## Usage

```bash
# Generate all scenes
python3 generate_video.py storyboard.md

# Preview prompts without making API calls
python3 generate_video.py storyboard.md --dry-run

# Concatenate clips into a single final MP4 after generation
python3 generate_video.py storyboard.md --concat

# Retake specific scenes only (uses the saved storyboard from the output dir)
python3 generate_video.py storyboard.md --scenes 3,7,11

# Retake + rebuild final video
python3 generate_video.py storyboard.md --scenes 3,7,11 --concat
```

### Options

| Flag | Default | Description |
|---|---|---|
| `--dry-run` | off | Print composed prompts and exit — no API calls |
| `--duration N` | `12` | Default clip duration in seconds (`4`, `8`, or `12`) |
| `--size WxH` | `1280x720` | Default resolution (`1280x720` landscape or `720x1280` portrait) |
| `--scenes N[,N…]` | all | Regenerate specific scene numbers only |
| `--concat` | off | Concatenate all clips into `<title>_final.mp4` using ffmpeg |

---

## Output

Clips are written to `./output/<storyboard-title>/`:

```
output/
  my-campaign/
    smart-home-day.md          ← storyboard snapshot (used for retakes)
    scene_01_title_take1.mp4
    scene_02_title_take1.mp4
    scene_03_title_take2.mp4   ← retake, original take1 preserved
    my-campaign_final.mp4      ← concat output (latest take per scene)
```

Every generation run saves clips as `take1`, `take2`, … — existing files are never overwritten. When `--concat` is used, the latest take of every scene is automatically selected.

---

## Writing a Storyboard

Copy `template.md` and fill it in. The structure is:

```
# Campaign Title
Global style description (prepended to every scene prompt).

## Voice          ← optional narrator voice profile
## Roles          ← one H3 per character
## Scenery        ← one H3 per location
## Scenes         ← one H3 per clip
```

See `template.md` for a full annotated example.

### Tips for character consistency

Sora generates each clip independently — physical specificity is the main lever for reducing variance across scenes:

- Specify age, height, build, skin tone, exact hair (length, colour, texture, parting), eye colour, and brow shape.
- End the global style paragraph with: *"Character appearance is consistent across every scene: same face, same hair, same build."*
- Keep each scene to a single beat (~40 words for 8 s, ~60 words for 12 s).

---

## API limits (Azure Sora 2)

| Parameter | Supported values |
|---|---|
| Duration | `4`, `8`, `12` seconds |
| Size | `1280x720` (landscape), `720x1280` (portrait) |
| Concurrent jobs | 2 (enforced automatically) |

The endpoint must **not** have `/videos` appended — the SDK adds the path automatically. See `.env.example`.
