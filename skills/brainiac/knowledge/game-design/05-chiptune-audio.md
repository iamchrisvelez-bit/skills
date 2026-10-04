# Chiptune Audio

## The classic channel set
- **Two pulse (square) channels** — melody and harmony. Duty cycles 12.5%, 25%, 50% change timbre from thin to hollow.
- **Triangle channel** — bass lines and soft leads.
- **Noise channel** — drums, explosions, wind.
In WebAudio, `OscillatorNode` types `square` and `triangle` cover the tones; a short buffer of random samples through a filter makes noise.

## Sound effects recipes
- **Jump**: square wave sweeping up quickly (e.g. 300 → 600 Hz over 0.1 s).
- **Coin/pickup**: two quick rising notes (e.g. B5 then E6).
- **Hit/damage**: noise burst with a falling square underneath.
- **Power-up**: rapid rising arpeggio.
- **Door/teleport**: slow sweep with vibrato.
Keep effects under ~0.3 s and use an envelope (fast attack, quick decay) to avoid clicks.

## Music
Write short loops (8–16 bars) per region. Fast arpeggios fake chords on a single channel. Give each region a recognizable motif and vary tempo/key between calm and dangerous areas. Always provide a mute toggle and start audio only after a user gesture (browser autoplay rules).
