# Attribution status

The inherited `arch/license_check.py` inventory currently identifies 8,888
assets through directory-local license records and reports 526 assets without
a matching record. Extraction preserves this state; it does not infer missing
rights or assign licenses without evidence.

Every release carries the existing attribution files beside a digest manifest.
New or moved assets must have explicit coverage, and cleanup work should reduce
the inherited gap by tracing original sources and authors. A zero-gap inventory
is the target, but inaccurate attribution is worse than an explicit unresolved
entry.

