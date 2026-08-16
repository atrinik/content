# Celestial-v1 content migration

Issue #181 migrates the authored source on `content@main` to the breaking
Classic celestial contracts. Every authored map is versioned with
`celestial_schema 1` and an explicit `sky_above` anchor. Existing horizontal
tile links retain their reciprocal topology and receive matching continuous
or discontinuous boundary records; no indoor rectangle is generated from
`map_info`.

The migration inventory is [`maps/celestial-migration-index.json`](../maps/celestial-migration-index.json).
It records the predecessor and migrated file digests, resolved region,
sky-anchor disposition, legacy ambient decision, and every stable dynamic
aperture ID. The inventory is generated from the exact `content@main`
predecessor and the Classic-compatible target SHA recorded in its header.

Legacy fields have one explicit disposition:

- `outdoor` is removed from every map and never becomes a per-cell exposure
  toggle.
- `darkness` is removed. On former outdoor maps it is ignored as a lighting
  authority; on non-outdoor maps the frozen table is translated once to the
  neutral `light` header (`-1, 1, 2, 3, 4, 5, 6, 7` → `0, 20, 40, 80, 160,
  320, 640, 1280`).
- `map_info` remains presentation/world-maker metadata and is not translated
  into structural exposure.
- `region` omissions become explicit `world` records.

The dedicated fixture family covers an outdoor street, a mixed linked house,
a courtyard/open shaft exception, a three-storey stack, an underground cave,
and glass/grate transmission. Regional fixture children exercise independent
solar/lunar inheritance, fixed/scaled rates, phase offsets, replacement RGB
endpoints, and zero/dim/bright brightness values.
