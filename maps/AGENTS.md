# Map and quest guidance

- This guide applies below `maps/`. The repository-root guide remains in force.
- Preserve map headers, coordinates, exits, tiled-map links, region membership,
  spawn semantics, event bindings, and reset behavior. Paths are content-root
  relative, case-correct, and portable.
- Preserve the byte and semantic behaviors characterized by
  `contracts/content-v1`; a header, nested-object, message, custom-field, line-
  ending, or serialization change requires an inventory/corpus update and an
  explicit compatibility decision.
- Keep quest, NPC, region, faction, and script identities stable. Do not use a
  display name or runtime table position as a durable cross-reference.
- Embedded Python must keep engine-owned entry points and deterministic state
  transitions. Validate missing objects, repeated events, partial progress,
  reload/reset, and failure cleanup where relevant.
- Update both ends of exits and tiled-map links. Trace referenced archetypes,
  interfaces, treasures, artifacts, factions, sounds, and images before moving
  or deleting content.
- Use `python3 tools/world_content_audit.py quests`, `regions`, or `world` for
  exploratory summaries, then rely on `python3 tools/validate.py` and the
  catalog for acceptance.
- Use the standalone map checker through its released catalog dependency when a
  visual or legacy-map scan is needed; never copy its parser into this tree.
- Update this guide with any major map, quest, or script rework that changes
  these ownership, identity, layout, runtime, or validation contracts.
