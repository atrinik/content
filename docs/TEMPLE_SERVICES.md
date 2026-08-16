# Temple recovery pricing

Temple recovery uses an explicit service rank and a deterministic quote. NPC
combat level is inventory evidence, not priest proficiency: the 27 providers
range from effective combat level 1 to 115 and include guards, an ogre, a
vampire, a raas, witches, and other non-priest archetypes.

## Affordability evidence and newcomer policy

The Incuna start gives no currency. An early quest outcome gives 50 copper and
its combat outcome gives 15 silver. Before this policy, level-1 recovery cost
5 silver 90 copper for depletion, 5 silver for poison, 10 silver for disease,
30 silver for curse removal, and 50 silver for damnation removal. Those fixed
fees could therefore turn an early condition into a progression deadlock.

Historically, depletion, disease, and poison treatment were free below level
3. Classic now suppresses normal death depletion through character level 3.
The policy aligns those safeguards: patients at or below level 3 receive free
depletion, disease, and poison treatment when condition difficulty is at most
5. Curse and damnation removal remain paid because the historical grace
deliberately excluded inventory curses. A harder condition is never subsidized
solely because its carrier is new; it receives the normal quote and still
requires a capable provider.

## Provider capability

The central registry identifies each provider by its stable authored map path
and NPC name, and maps that pair to one reviewed service rank:

| Rank | Role | Providers |
| ---: | --- | --- |
| 20 | Community | Brelend Lee, Manzom, Telath, Marcus Stephen, Thumron, Helga, Eshorem, Oxa, Jania, Merithax, Ugthar, Morvarm, Cthisss, Alcrom, Murfar |
| 40 | Regional | Hivro Holygauntlet, Sakura, Ami, Saruthar, Celach Dawson, Filbreena Ulass |
| 60 | Senior | Conuld Burch, Friar Marcus, Talrain, Traba Jainkoaren, Gwenty |
| 100 | High priest | Archbishop Theodorus III |

The content validator discovers standard, special, and quest-gated temple
interfaces and requires those 27 authored identities to match the registry exactly.
Combat-level outliers such as level-1 Manzom (service rank 20), level-115
Talrain (rank 60), and level-68 Archbishop Theodorus III (rank 100) prove that
the capability input is independent.

Condition difficulty is the highest disease, poison, cursed-item, or
damned-item level within that native spell's existing scope. Remove damnation
also sees ordinary curses because Classic's spell already handles both; this
policy does not expand it. Depletion difficulty is the greater of its object level and
five times the total depleted stat points. A provider refuses a condition when
difficulty exceeds service rank. During the synchronous spell call, the NPC's
effective level is temporarily set to its service rank and restored in a
`finally` block, so Classic's disease and curse capability checks use the same
reviewed input as the quote.

## Full-price curve

For paid care, the unrounded copper price is:

```text
base + patient_level * patient_factor
     + condition_count * condition_factor
     + difficulty * difficulty_factor
     + depletion_severity * severity_factor
```

An easy case treated by a provider above the required rank receives a
capability discount of one percent per two surplus ranks, capped at 30%. The
discounted result is rounded down to 10 copper, then clamped to the service
minimum and maximum.

| Service | Base | Patient | Condition | Difficulty | Severity | Minimum | Maximum |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Remove depletion | 200 | 45 | 75 | 10 | 100 | 100 | 12,000 |
| Cure disease | 300 | 50 | 100 | 20 | 0 | 100 | 15,000 |
| Cure poison | 150 | 35 | 75 | 15 | 0 | 100 | 8,000 |
| Remove curse | 750 | 60 | 150 | 20 | 0 | 100 | 18,000 |
| Remove damnation | 1,250 | 80 | 200 | 30 | 0 | 100 | 25,000 |

Examples, all in copper:

| Case | Rank | Quote |
| --- | ---: | ---: |
| Level-3 patient, difficulty-5 poison | 20 | free |
| Level-4 patient, difficulty-4 poison | 20 | 390 |
| Level-4 patient, one-point depletion (difficulty 5) | 20 | 560 |
| Level-1 patient, difficulty-1 curse | 20 | 890 |
| Level-20 patient, difficulty-20 disease | 20 | 1,800 |
| Same disease and patient | 100 | 1,260 |
| Level-100 patient, difficulty-100 disease | 100 | 7,400 |

Patient level, condition count, difficulty, and depletion severity all make an
otherwise equivalent quote nondecreasing. Greater surplus provider capability
can only reduce the quote. Integer arithmetic, explicit rounding, and bounds
make the result reproducible.

## Confirmation and settlement

Preview and confirmation both use the same quote function. The confirmation
link carries the service, price, count, difficulty, severity, provider rank,
and a digest of condition evidence. Confirmation re-snapshots and requotes; a
changed token produces a new preview and no cast or payment.

The transaction checks funds before casting, then compares synchronous pre-
and postconditions before collecting payment:

- no condition: refuse, do not cast, and do not charge;
- insufficient funds: do not cast and do not charge;
- total failure: report failure and do not charge;
- full success: charge exactly the displayed quote;
- partial success: identify the remaining condition and charge exactly the
  displayed quote, because the provider was prequalified for the complete
  snapshot and delivered beneficial treatment;
- repeated confirmation: the cured condition no longer exists, so do not cast
  or charge.

The individual `remove depletion`, `cure disease`, `cure poison`, `remove
curse`, and `remove damnation` spells remain separate. This policy does not
change `restoration` or broaden any spell's scope.
