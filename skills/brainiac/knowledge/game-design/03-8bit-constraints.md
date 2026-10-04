# The 8-Bit Aesthetic: Constraints as Style

## Resolution and grid
- Classic consoles render around **256×240** (NES) or **160×144** (Game Boy). Pick a low internal resolution and scale up by an integer factor with nearest-neighbour sampling (`image-rendering: pixelated`, `ctx.imageSmoothingEnabled = false`).
- Build everything on a tile grid: **8×8** base tiles, **16×16** metatiles for terrain and characters.
- Snap camera and sprite positions to whole pixels; sub-pixel drawing breaks the look.

## Palette
- Use a fixed master palette (NES had ~54 usable colours) and give each sprite **3 colours + transparent**. Each background area uses a small sub-palette.
- Choose colours by value first: dark outline, mid body, light highlight. Test the art in greyscale — if it reads, the palette works.
- Shift hue as you shift value (shadows cooler, highlights warmer) for richer ramps from few colours.

## Sprites
- A 16×16 hero should read as a silhouette at a glance. Exaggerate the head, hands and feet.
- 2–4 frame animations are enough: idle bob (2), walk (2–4), action (1–2). Hold frames ~8–12 game ticks.
- Use a 1-pixel dark outline on characters to separate them from busy backgrounds.

## Tiles
- Tiles must tile seamlessly. Break repetition with 2–3 variants placed with a deterministic pattern or hash.
- Background detail should be lower contrast than the playfield.

## Text and UI
- Use a bitmap font on the 8-pixel grid. Keep the HUD in a dedicated strip so it never overlaps play.
- Display numbers with leading zeros (SCORE 000450) for the period look.

## Effects that stay authentic
Palette swaps (flash white on hit), screen shake in whole pixels, sprite flicker for invulnerability, dithering for gradients, and simple particle squares.
