# Vigil design assets: sources and prompts

Every image here was generated with ChatGPT image generation, prompted by the owner, on
2026-11-01 unless noted. It follows the Look v2 direction (Sonar brand, Watch Floor product,
Industrial world) with the paler ice accent the owner chose on 2026-11-01. How each is used:
`docs/ui.md`, Look v2.

| File | What it is | Use | Status |
|---|---|---|---|
| `visual-identity-v2.png` | The Look v2 exploration sheet (owner, 2026-10-31) | Reference | Reference |
| `vigil-orb-states.png` | The advisor's avatar, the "sonar orb": 5 states at full size, 32 px and 16 px | Reference for the inline SVG built in UI-3a | Final reference (PNG) |
| `vigil-bg-mast.webp` | Point-cloud mast and factory skyline, full strength | Login, `/watch`, empty states | Final, 2560×1440 (WebP, 78 KB). |
| `vigil-bg-mast-dim.webp` | The same image, darker and blurrier | Behind `/talk` with frosted panels | Final, 2560×1440 (WebP, 23 KB). A thin stray band at the top edge of the export was trimmed (34 px) and the image re-scaled to 2560×1440. |

Not committed: two superseded first-round images (a photographic mast on a foggy hill, and a
point-cloud tower over a factory with a moon).

**Shipping rules:** served from the repo, never fetched; WebP at most 200 KB each (the two
backgrounds are 78 KB and 23 KB, `cwebp -q 82 -m 6`); operational pages (`/`, `/jobs`,
`/job/:id`, `/review`) stay flat, with at most the dim variant at about 6% opacity behind the
left nav.

## Background prompt (final round)

```
16:9, 2560x1440, background art for a dark control-room UI; no text, no logos, no moon, no people.
Composition: a steel lattice communications mast on a hill on the right third, low foggy horizon, the left half calm dark sky (#05080B to #121A22) kept empty for UI.
Rendering: the mast and a faint distant factory skyline are partly reconstructed as a sparse 3D point cloud of tiny pale ice-white and white-blue points (#EAF6FC, #D6F1FB, #B8E7F8), denser at the tower top, dissolving into fog toward the left. One soft pale beacon at the mast top, not saturated cyan. Horizon glow very dim and low (below 85% of frame height). Heavy atmospheric blur everywhere except the upper tower. Desaturated, cold, quiet.
Then give a second version: same image, 40% darker and blurrier, for use behind chat panels.
```

Follow-up used to get full-size files: "Give me the top image alone as a single 2560×1440 PNG,
then the bottom (dim) version alone at 2560×1440."

## Orb prompt (final round)

```
Redo the "orb" from the sprite sheet: same 5 states (idle, thinking, speaking, waiting, alert). Dots are near-white (#EAF6FC) cores with a faint pale ice-blue halo (#B8E7F8), not saturated cyan. Inner ring dots smaller and dimmer. Show each state also at 16px and 32px next to the large version, on #05080B. Flat, geometric, crisp edges.
```

First-round orb prompt: an original abstract "sonar orb" of 16–24 dots in 2–3 concentric
rings, not resembling any existing assistant logo; five states (idle, thinking, speaking,
waiting for the owner, alert); alternates lantern and owl (not chosen).

## The orb as shipped (UI-3a)

One inline SVG of at most 2 KB with CSS state classes. Idle is a slow breathe; thinking has
the dots orbiting, uneven; speaking has the outer ring rippling outward; waiting has one dot
bright and the rest dim; alert has the rings tightened and all bright. At 16 px it is a
single ring of 8–12 dots. No motion under `prefers-reduced-motion`. Later, coord gets the
same dots in a square grid and workers a single row.
