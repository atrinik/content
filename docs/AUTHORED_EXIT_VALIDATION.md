# Authored exit validation

`tools/validate_exits.py` checks the statically resolvable destination of each
authored Classic exit. Every statically provable non-enterable destination is a
validation error, including findings already present in the authored corpus.

Run a standalone check with:

```sh
python3 tools/validate_exits.py --root . --check
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
without a usable landing are errors. The human-readable command output includes
the source and target locations; `--json` exposes the complete diagnostic
records.

Dynamic, scripted, permission-gated, player-specific, and otherwise
unresolvable activation rules are outside this static verdict and are counted
in the report's `excluded` section. The validator has no authored-content side
effects.
