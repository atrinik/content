# Scripted gameplay audit boundaries

`maps/python/scripted-gameplay-audit-v1.json` is the reviewed, fail-closed
inventory of every authored Python gameplay metric call. The aggregate
validator parses the source with Python's AST, rejects dynamic metric names,
and requires the manifest to match every path, method, metric identity, and
occurrence exactly. New or removed sites therefore require an explicit noise,
privacy, and recovery decision.

The four dispositions match the server gameplay-journal taxonomy:

- `gameplay-journal` is a bounded semantic transition useful for support or
  recovery. Its stable reason is server-validated and contains no player text.
- `aggregate-only` retains bounded statistics without ordered event evidence.
- `operational/security-log` remains protected human/operator diagnostics.
- `not-recorded` is neither useful nor appropriate to retain.

All 26 current metric calls are low-volume quest, post, auction, merchant,
housing, bounty, guild, or jail outcomes and are classified as projections of
gameplay-journal transactions. Existing metrics remain at their current
semantic success boundary and must advance once only after the corresponding
business transaction commits. Generic payment or custody hooks must not add a
second copy of a business-specific aggregate.

The existing guild-storage `Guild.log_add` calls are separately classified as
operational/security logging. They include display names and, for privileged
bulk commands, arbitrary command text. That text must not enter structured
gameplay records. Successful storage custody instead belongs to the server's
typed item transaction at the authoritative post-veto move boundary.

High-volume movement, traversal, attacks, ordinary kills, damage, healing,
regeneration, routine spell/skill/consumable use, chat, emotes, and every
intermediate quest-state write have no scripted metric sites and remain
unrecorded by authored Python. Adding one requires a new reviewed manifest row;
it never becomes a journal producer merely because a metric is useful.

The executable transaction integration depends on the stable quest contract in
https://github.com/atrinik/classic/issues/161 and the scripted multi-step
economy composition contract in https://github.com/atrinik/classic/issues/313.
Content must use those typed APIs rather than append raw logs, invent a second
audit store, or misuse quest/progression records for item and currency flows.
