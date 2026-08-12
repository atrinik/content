# Power-crystal light lifecycle review

Issue #95 was exercised against these immutable authored/runtime inputs:

- content authored commit: `2f786326601deaab4e21edb3ea86d68240add097`;
- Classic client/server commit: `7ad4acc27c222db7ce3e74d7db5ac93e9464cd28`;
- resources commit: `266ac693e5567e1c253384bff1d490f1e37fedca`;
- wrapper profile: `issue-95-power-crystal-runtime`;
- topology: `issue-95-power-crystal`;
- scenario: `issue-95-power-crystal`;
- state: `scenario-issue-95-power-crystal`.

The review-only `tools/light-source-review/dark-lab` map was staged only in the
isolated topology. The scenario account was provisioned by the wrapper; no
credential or mutable scenario state is part of this record.

## Deterministic assertions

Each row below records the decisive Classic Python-console operation and the
assertion that completed without `AssertionError` or traceback in the server
log. Object names use the `issue95v_` prefix so the run can remove stale test
objects before every sequence.

| Lifecycle state | Operation and asserted result |
| --- | --- |
| Clean control | Remove all named review objects; assert `activator.glow_radius == 0`. |
| Ground | Create `power_crystal` on the map; assert object radius `1`, color `0xfff0c0`, and carrier radius `0`. |
| Pickup | Insert the ground crystal directly into the player; assert carrier radius `1` and color `0xfff0c0`. |
| Drop | Insert the crystal back into the map; assert carrier radius `0` and object radius `1`. |
| Direct inventory | Create `power_crystal` directly in the player; assert radius `1` and color `0xfff0c0`. |
| Nested container | Move the direct crystal into a carried `sack`; assert carrier radius `0`; move it back directly and assert radius `1`. |
| NPC inventory | Create a stationary `woman` with a contained crystal; assert both player and NPC aggregate radii remain `0`. |
| Trade | Move the NPC crystal directly to the player; assert player radius `1`. |
| Shop stock | Mark the directly carried crystal unpaid and retain radius `1`; move unpaid stock into the merchant NPC and assert both aggregate radii are `0`. |
| Multiple and upgraded crystals | Carry the base crystal with `mana_crystal_100`; assert the aggregate remains radius `1`; destroy the upgrade and assert it remains radius `1`. |
| Stronger equipped light | Apply a radius-3 `torch` while carrying a crystal; assert radius `3` and `0xffc080`; add `mana_crystal_100` and retain the torch result; destroy the torch and assert fallback to radius `1` and `0xfff0c0`. |
| Map transition | Teleport with the direct crystal from the lab to Marigold at `(22,10)` and back; after each transfer assert the object exists and carrier radius is `1`. |
| Logout/login | Save the direct crystal, cleanly stop the topology, restart the same profile/scenario/state, and log in again; assert the object exists with radius `1` and color `0xfff0c0`. |
| Death/respawn | With the saved direct crystal and test-GM mode disabled, assert radius `1`, set HP to `-1`, and allow the Classic player process to execute death/respawn; assert the restored inventory object, radius `1`, and `0xfff0c0`. Nesting it immediately afterward produced radius `0`, proving no stale source; returning it directly restored radius `1`. Test-GM mode was restored and the state saved. |

The successful carrier/NPC/trade/upgrade/transition sequence is recorded from
`2026-08-11T09:59:49Z` through `10:00:44Z`. Clean logout occurred at
`10:03:44Z`; the same character logged in at `10:06:02Z`, and relogin
assertions completed at `10:06:28Z` and `10:06:30Z`. Death/respawn and the
post-death stale-source checks completed from `10:07:28Z` through `10:07:42Z`.
The independent ground/pickup/drop/torch-precedence sequence completed from
`10:12:56Z` through `10:13:14Z`.

The pinned Classic checkout also built `atrinik-server-tests` from commit
`7ad4acc27c222db7ce3e74d7db5ac93e9464cd28`. The focused command

```sh
ctest --test-dir /workspaces/atrinik/workspace/build/profiles/issue-95-power-crystal-runtime-eca840d37182/build/integrated \
  -R '^server-unit-types\.light_apply$' --output-on-failure
```

passed all 14 `types.light_apply` cases, including stable strongest-light
selection, non-amplifying equal-radius inventory lights, removal/reinsertion,
map transfer/reload, and save/load reconstruction.

## Semantic and field preservation

The semantic review ledger binds the base `power_crystal`, each of its six
artifact variants, and the visible Marigold world instance to their effective
source digests. Rendered review images are generated output and are not kept in
the authored content repository.

The authored diff adds only `glow_radius 1` and `light_color fff0c0` to the
base archetype. The lossless validator and semantic inventory confirm that
charge capacity, mana value, artifact identity, quest upgrade fields,
merchant stock, rarity, value, weight, face, animation, and the remaining
gameplay fields are unchanged.
