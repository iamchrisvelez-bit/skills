# Production: Scoping, Building and Polishing

## Scope
Ship a small complete game rather than a large broken one. A strong first release: one hero with 2–3 verbs, 3–4 enemy types, 1 boss or climax, 10–20 rooms, a title screen, a win screen, and a game-over/retry loop.

## Build order
1. Movement and collision in an empty room — tune until it feels good.
2. One enemy and one hazard; damage, death and respawn.
3. Room transitions and a world map in data, not code.
4. Collectibles, HUD, win condition.
5. Art pass, audio pass, juice pass.
6. Title screen, pause, settings (mute), instructions.

## Data-driven worlds
Describe rooms as strings or arrays of tile characters so new content is data, not code. Keep entities (enemies, items, doors) in a separate layer from terrain.

## Playtesting
Watch someone play without helping. Note where they hesitate, die repeatedly, or get lost. Fix confusion before adding content. Measure: time to first death, time to complete, where players quit.

## Accessibility
Remappable or dual key layouts (arrows + WASD), no information conveyed by colour alone, a mute toggle, readable text sizes, and no rapid full-screen flashing.

## Definition of done for a game build
Starts from a title screen, can be won, can be lost and retried, has audio with a mute, runs at a steady 60 fps, and has no softlocks (every room can be exited).
