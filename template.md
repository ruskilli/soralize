# Product Launch Campaign
Cinematic, documentary-style footage. Warm colour grading with shallow depth of field.
Handheld camera feel. Soft natural light throughout. No text overlays.
[Describe the overall visual tone, camera style, and mood here. This is prepended to
every scene prompt to ensure visual consistency across all clips. End with a sentence like
"Character appearance is consistent across every scene: same face, same hair, same build."
to anchor cross-scene character consistency.]

## Voice
- gender: female
- language: English
- style: warm, calm, and conversational
- accent: neutral
[Optional. Defines the default voice-over narrator profile. All keys are optional.
Valid gender values: female, male, neutral.
Per-scene overrides available via voiceover-gender, voiceover-language,
voiceover-style, voiceover-accent keys in individual scenes.]

## Roles

### Maya
Young woman, late twenties. Slim build, approximately 165 cm. Medium-deep skin tone.
Short natural dark hair, close-cropped sides. Warm brown eyes, defined brows, clean complexion.
Confident posture, warm smile, relaxed jaw.
[Character appearance is consistent across every scene: same face, same hair, same build.]
[TIP: Physical specificity is the main lever for cross-scene consistency. Include: age,
build/height, skin tone, exact hair length/colour/texture, eye colour, brow shape, and
any distinctive features. Vague descriptions (e.g. "dark hair") give the model more room
to vary. Include outfit variations by scene range if the character changes clothes, e.g.:
  Morning scenes (Scenes 1–2): casual outfit.
  Work scenes (Scenes 3–4): formal attire.]

### Daniel
Man in his early forties. Wearing a navy blazer over a light grey t-shirt.
Greying temples, slight stubble, calm and approachable expression.

## Scenery

### Modern Office
Bright open-plan workspace with floor-to-ceiling windows. White walls, wooden desks,
green plants everywhere. Morning light streaming in from the left.
[Describe the setting in detail: lighting, materials, mood, time of day.
This is injected into every scene that references this location.]

### Coffee Shop
Cosy independent coffee shop. Exposed brick walls, mismatched wooden furniture,
warm Edison-bulb lighting. Background chatter barely audible.

### Rooftop Terrace
Urban rooftop at golden hour. City skyline in the distance, potted plants along
the railing, string lights beginning to glow. Gentle breeze.

## Scenes

### Scene 1: Maya Opens Her Laptop
- character: Maya
- location: Modern Office
- duration: 12
- size: 1280x720
- voiceover: Your work day begins before you even sit down.
- background-sound: Quiet office ambience, soft keyboard clicks nearby.

Maya sits down at her desk and opens a sleek laptop. She glances at the screen
with quiet satisfaction and begins typing.
[Action text: keep this single-purpose. One clear beat per scene gives Sora
the best result. Aim for ~40 words for 8s clips, ~60 words for 12s clips.
Supported durations: 4, 8, or 12 seconds.
Supported sizes: 1280x720 (landscape) or 720x1280 (portrait).
voiceover and background-sound are both optional.]

### Scene 2: Daniel Grabs His Coffee
- character: Daniel
- location: Coffee Shop
- duration: 8
- size: 1280x720
- background-sound: Gentle cafe ambience, espresso machine in the background.

Daniel picks up a takeaway coffee cup at the counter and takes a slow first sip.
He looks relaxed, gazing slightly off-camera.

### Scene 3: Maya on the Rooftop
- character: Maya
- location: Rooftop Terrace
- duration: 12
- size: 1280x720
- voiceover: Sometimes the best ideas come when you step away.
- voiceover-style: reflective and warm

Maya leans against the rooftop railing, looking out over the city skyline.
She turns to camera with a composed, natural smile.
[voiceover-style overrides the global ## Voice style for this scene only.
Other per-scene overrides: voiceover-gender, voiceover-language, voiceover-accent.]

### Scene 4: Daniel Back at the Office
- character: Daniel
- location: Modern Office
- duration: 12
- size: 1280x720

Daniel walks through the office and pauses to glance at a large monitor showing
a colourful graph. He nods with quiet approval.

