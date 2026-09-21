# SceneFlow Motion Templates

`MotionShot.tsx` contains the first eight deterministic templates produced by
`motion/template_router.py`:

- `M_TITLE`
- `M_COMPARE`
- `M_LIST`
- `M_TIMELINE`
- `M_NUMBER`
- `M_RANKING`
- `M_PROCESS`
- `M_GALLERY`

All templates consume the same props: `duration`, `title`, `items`, `images`,
`numbers`, `highlight_index`, and `aspect_ratio`. The router supports `9:16`,
`1:1`, and `16:9` without hard-coded landscape dimensions.
