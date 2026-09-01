# Authored exit validation

`tools/validate_exits.py` checks the statically resolvable destination of each
authored Classic exit. The normal content validator runs this check against the
reviewed migration baseline in `tools/exit-validation-baseline.json`.

Run a standalone check with:

```sh
python3 tools/validate_exits.py --root . --baseline tools/exit-validation-baseline.json --check
```

The check resolves these authored forms deterministically:

- explicit paths and coordinates;
- same-map coordinates;
- tiled exits, including horizontal map-edge coordinate resolution and xray
  direction offsets;
- automatic-link exits using the Classic five-square peer search; and
- shop-mat exits using their automatic-link subtype.

For a path-based destination, the requested cell is checked first. If it is not
usable for a normal player, the validator checks the eight adjacent cells,
matching Classic's bounded landing fallback. A usable landing has a floor, no
blocking object, and terrain compatible with the normal player terrain mask.
Fixed-position exits do not use the adjacent fallback.

Diagnostics include a stable identifier, source file and line, source
coordinate, exit form, requested and resolved target, reason code, and a
deterministic explanation. Missing maps, invalid coordinates, and destinations
without a usable landing are errors.

Dynamic, scripted, permission-gated, player-specific, and otherwise
unresolvable activation rules are outside this static verdict and are counted
in the report's `excluded` section. The validator has no authored-content side
effects.

The baseline records the findings already present in the corpus while the
companion map-repair issue is delivered. It is intentionally exact: new
findings fail validation, and a finding disappearing without its baseline being
updated is reported as stale. After the companion repairs are complete, the
baseline can be removed in that separately authorized delivery.
