# SHARDLIGHT: The Bottled Isles — Design Document

*A Brainiac world. Self-contained: one HTML file, no shared code or assets with any other environment.*

## Premise
A collector intelligence sealed the isle of Lumen inside a glass bottle and put out its
Beacon. Mote, the last lantern-keeper, has to gather five Star Shards, wake the Beacon,
and crack the glass from the inside.

## Target feeling (aesthetics → mechanics)
| Feeling | Mechanics that produce it |
|---|---|
| Discovery | Flip-screen map with visible-but-unreachable shards, crystal walls that hint at secrets, a minimap that fills in |
| Competence | Three verbs that combine, readable hazards, fair checkpoints |
| Tension and release | Hazard rooms alternate with calm rooms; the boss builds to a phase change |

## Verbs (three, each used more than one way)
- **Move**: fast acceleration on ground, slippery on ice.
- **Spark** (Z/Space): kills enemies **and** breaks cyan crystals to open secrets.
- **Dash** (X/Shift): dodges enemies, **skims water** and **crosses spikes safely**. It has
  invulnerability frames, so it's a traversal tool and a defensive tool at once.

## Colour language (kept the same everywhere)
- **Magenta = harm**: spikes, enemy orbs, the turret's wind-up glow, the boss's enraged eye.
- **Cyan crystal = breakable** with a spark.
- **Gold = reward**: shards, keys, the Beacon.

## World map (4×3 rooms, 16×12 tiles of 16 px)
```
 [WINTER SPIRE*]─[FROST GATE]─[CLOCKWORK GATE]═seal═[THE CORE: Warden + Beacon]
                      ║ key door
 [PRISM CAVE*]───[HOLLOW HUB]─[BAT ROOST*]──────[SUNKEN HALL: key]
       │              │                              │
 [WHISPER MEADOW*]─[START GLADE]─[BROOKSIDE]────[GLASS SHORE*]
```
`*` = Star Shard. The seal opens at 5/5 shards; the Hub's north door needs the key.

## Teaching sequence (introduce → develop → twist → conclude)
1. **Start Glade** puts a heart behind crystals. The banner says "SPARK BREAKS CRYSTAL". No enemies, nothing at stake.
2. **Whisper Meadow** develops it: the shard sits behind a crystal, with slimes for mild pressure.
3. **Brookside** introduces dash. A one-tile stream crosses the whole room and the banner explains it. Falling in costs one heart and puts you back on the bank.
4. **Glass Shore** tests it: the shard is on an island two tiles out.
5. **Bat Roost** twists it: the shard is ringed by spikes, and dashing over them is safe.
6. **Sunken Hall** combines dash, turrets and water to reach the key.
7. **Frost** regions add ice physics (low traction) next to spikes.
8. **Clockwork Gate** has spike columns, turrets and a safe lane along the bottom.
9. **The Core** is the conclusion: the Warden of Glass. Telegraphed ring volleys, then at half health a faster phase 2 with denser rings plus aimed shots.

## Game feel
- Input buffer (8 frames) for spark and dash. Corner-nudging around doorways.
- Hit-stop on every impact (3–20 frames), screen shake, white-flash on enemies, particle bursts.
- Invulnerability flicker after damage, plus knockback away from the source.
- Enemy hitboxes are smaller than their art. Pickup hitboxes are generous.
- Turrets and the boss telegraph 30–40 frames before firing, with a visual glow and a sound.
- Collecting things in quick succession raises the pitch of the pickup sound.

## 8-bit constraints honoured
- 256×224 internal resolution, scaled by whole numbers with nearest-neighbour sampling.
- 16×16 metatiles, sprites with 3–4 colours plus transparency, a 1 px dark outline on characters.
- Tiles are generated deterministically from per-region 3-step colour ramps, with hashed variants to break up repetition.
- The HUD has its own strip: hearts, shard count, key, dash-ready indicator, minimap and room name.

## Audio
Pure WebAudio chiptune: square-wave lead, triangle bass and noise drums. Each region has its own loop (bright C-major meadow, minor-key caves, sparse high frost, driving clockwork, tense chromatic core). Every action has a sound effect. **M** mutes.

## Fairness and retry
Dying ("YOU FADED") restarts you at the room entrance with full hearts, and you keep your shards, keys and opened doors. Collecting a shard refills your hearts. There are no softlocks: an automated flood-fill check confirms every exit and item is reachable.

## Definition of done (from the curriculum)
- [x] Title screen → play → win screen with time and death stats
- [x] Can be lost and retried
- [x] Audio with mute
- [x] Fixed 60 Hz simulation step
- [x] No softlocks (verified by automated reachability check)
- [x] Keyboard (arrows/WASD) and touch controls
