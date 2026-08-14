# Scripted gameplay audit boundaries

`contracts/scripted-gameplay-audit/v1.json` is the reviewed, fail-closed
inventory of every authored Python gameplay metric and audit-like logging call.
The aggregate validator parses all `maps/**/*.py` source except test fixtures,
rejects dynamic or indirect metric access, and binds every call to its source,
lexical scope, AST location, and a normalized hash of the surrounding function
or module. Moving, adding, removing, or semantically surrounding a site
therefore requires an explicit noise, privacy, and recovery decision.
The telemetry spellings `Metric*`, `Logger`, `print`, and `log_add` are reserved
within authored maps; ambiguous shadowing, rebinding, or reflection is rejected.

The four dispositions describe the intended telemetry boundary:

- `gameplay-journal` is a bounded semantic transition useful for support or
  recovery. Its proposed reason is ASCII, bounded to the Classic server's
  255-character gameplay-journal identifier limit, and contains no player
  text. The Classic server contract is authoritative; quest lifecycle producers
  now use it, while economy producers remain gated on the composition API.
- `aggregate-only` retains bounded statistics without ordered event evidence.
- `operational/security-log` remains protected human/operator diagnostics.
- `not-recorded` is neither useful nor appropriate to retain.

All 26 current metric calls are low-volume quest, post, auction, merchant,
housing, bounty, guild, or jail outcomes classified as gameplay-journal
projections. Quest lifecycle producers now use the stable Classic contract.
This classification does not claim that the remaining legacy economy placement
is transactionally safe. Merchant purchase metrics currently
precede item or spell delivery, post collection precedes queue removal, and
housing metrics can follow debit while preceding the ownership or fee update.
They must move behind the durable idempotent commit/reconciliation result when
the typed APIs become available; generic payment or custody hooks must not add
a second copy of a business-specific aggregate.

The 16 current audit-like sites include generic Python diagnostics and prints,
guild chat and console commands, guild-storage `Guild.log_add` calls, and their
human-text file sink. Some carry
display names or arbitrary operator/player text. That text must not enter
structured gameplay records. Successful storage custody instead belongs to the
server's typed item transaction at the authoritative post-veto move boundary.

High-volume movement, traversal, attacks, ordinary kills, damage, healing,
regeneration, routine spell/skill/consumable use, chat, emotes, and every
intermediate quest-state write have no scripted metric sites and remain
unrecorded by authored Python. Adding one requires a reviewed contract row; it
never becomes a journal producer merely because a metric is useful.

The stable quest contract from https://github.com/atrinik/classic/issues/161 is
integrated by the shared `QuestManager`. Remaining executable economy
integration depends on the scripted multi-step composition contract in
https://github.com/atrinik/classic/issues/313. Content must use that typed API
rather than append raw logs, invent a second audit store, or misuse
quest/progression records for item and currency flows.
