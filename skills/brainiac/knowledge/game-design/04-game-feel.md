# Game Feel ("Juice")

## Input that feels right
- **Responsiveness**: act on the frame the input arrives. Never queue animations before movement.
- **Input buffering**: remember a jump/attack press for ~6–8 frames and execute it as soon as it becomes legal.
- **Coyote time**: allow a jump for ~6 frames after walking off a ledge.
- **Variable jump height**: cut upward velocity when the button is released.
- **Acceleration**: a few frames to reach top speed and a few to stop — instant is twitchy, slow is mushy.

## Feedback layers for an impact
Stack several small responses: sound, hit-flash (1–3 frames of white), knockback, **hit-stop** (freeze 2–4 frames), screen shake (1–3 px, decaying), particles. Each alone is subtle; together they sell the impact.

## Damage and fairness
- **Invulnerability frames** (~1 s) after taking damage, shown with flicker.
- Hitboxes for hazards slightly smaller than their art; hitboxes for pickups slightly larger.
- Telegraph enemy attacks with a wind-up (colour change, pause, sound) at least ~15 frames before they land.

## Camera
Lead the camera slightly in the direction of motion. In flip-screen games, transition with a quick slide (~15–20 frames) and pause enemies during it.

## Rewards
Collectibles should pop: a bounce, a sparkle, a rising pitch when collected in quick succession (combo pitch). Give the player a sound for every success.
