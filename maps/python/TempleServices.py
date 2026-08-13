"""Pure policy for Classic temple recovery quotes and provider capability."""

from collections import OrderedDict, namedtuple
import hashlib


Service = namedtuple(
    "Service",
    (
        "title spell base patient condition difficulty severity minimum maximum "
        "newcomer_essential"
    ),
)
Provider = namedtuple(
    "Provider", "name map_path interface combat_level service_rank"
)
Condition = namedtuple("Condition", "count difficulty severity fingerprint")
Quote = namedtuple(
    "Quote",
    "service cost count difficulty severity provider_rank free discount token",
)
Settlement = namedtuple("Settlement", "outcome charged after")


NEWCOMER_MAX_LEVEL = 3
NEWCOMER_MAX_DIFFICULTY = 5
ROUNDING_UNIT = 10
MAX_CAPABILITY_DISCOUNT = 30


SERVICES = OrderedDict((
    ("remove depletion", Service(
        "Removal of depletion", "remove depletion",
        200, 45, 75, 10, 100, 100, 12000, True,
    )),
    ("remove curse", Service(
        "Removal of curse from all cursed items", "remove curse",
        750, 60, 150, 20, 0, 100, 18000, False,
    )),
    ("remove damnation", Service(
        "Removal of damnation from all damned items", "remove damnation",
        1250, 80, 200, 30, 0, 100, 25000, False,
    )),
    ("cure disease", Service(
        "Curing of disease", "cure disease",
        300, 50, 100, 20, 0, 100, 15000, True,
    )),
    ("cure poison", Service(
        "Curing of poison", "cure poison",
        150, 35, 75, 15, 0, 100, 8000, True,
    )),
))


def _provider(name, map_path, interface, combat_level, service_rank):
    return Provider(name, map_path, interface, combat_level, service_rank)


PROVIDERS = OrderedDict((
    ("brelend-lee", _provider("Brelend Lee", "maps/shattered_islands/world_4_84", "quests/lost_memories/quest.xml", 20, 20)),
    ("manzom", _provider("Manzom", "maps/shattered_islands/world_13_4", "temples/elathiel.xml", 1, 20)),
    ("telath", _provider("Telath", "maps/shattered_islands/world_8_78", "temples/elathiel.xml", 20, 20)),
    ("marcus-stephen", _provider("Marcus Stephen", "maps/shattered_islands/world_6_42", "temples/elathiel.xml", 22, 20)),
    ("thumron", _provider("Thumron", "maps/shattered_islands/world_7_42", "temples/grumthar.xml", 22, 20)),
    ("helga", _provider("Helga", "maps/shattered_islands/world_7_43", "temples/grunhilde.xml", 22, 20)),
    ("eshorem", _provider("Eshorem", "maps/shattered_islands/world_7_43", "temples/tylowyn.xml", 22, 20)),
    ("oxa", _provider("Oxa", "maps/shattered_islands/world_7_44", "temples/shaligar.xml", 22, 20)),
    ("jania", _provider("Jania", "maps/shattered_islands/world_7_44", "temples/terria.xml", 24, 20)),
    ("merithax", _provider("Merithax", "maps/shattered_islands/world_8_43", "temples/dalosha.xml", 24, 20)),
    ("ugthar", _provider("Ugthar", "maps/shattered_islands/world_8_43", "temples/jotarl.xml", 22, 20)),
    ("morvarm", _provider("Morvarm", "maps/shattered_islands/world_8_43", "temples/zechna.xml", 25, 20)),
    ("cthisss", _provider("Cthisss", "maps/shattered_islands/world_8_43", "temples/rashindel.xml", 25, 20)),
    ("alcrom", _provider("Alcrom", "maps/shattered_islands/world_8_44", "temples/rogroth.xml", 28, 20)),
    ("murfar", _provider("Murfar", "maps/shattered_islands/world_8_44", "temples/drolaxi.xml", 22, 20)),
    ("hivro-holygauntlet", _provider("Hivro Holygauntlet", "maps/shattered_islands/strakewood_island/rockforge/rockforge_a_ab01", "temples/grumthar.xml", 50, 40)),
    ("sakura", _provider("Sakura", "maps/shattered_islands/world_0_53", "strakewood_island/centennial/sakura.xml", 30, 40)),
    ("ami", _provider("Ami", "maps/shattered_islands/world_-1_52", "strakewood_island/centennial/ami.xml", 30, 40)),
    ("saruthar", _provider("Saruthar", "maps/shattered_islands/world_3_58", "temples/elathiel.xml", 35, 40)),
    ("celach-dawson", _provider("Celach Dawson", "maps/shattered_islands/world_5_67", "temples/elathiel.xml", 35, 40)),
    ("filbreena-ulass", _provider("Filbreena Ulass", "maps/shattered_islands/world_2_48_-3", "temples/dalosha.xml", 37, 40)),
    ("conuld-burch", _provider("Conuld Burch", "maps/shattered_islands/world_2_68", "temples/elathiel.xml", 65, 60)),
    ("friar-marcus", _provider("Friar Marcus", "maps/shattered_islands/world_6_44_1", "temples/elathiel.xml", 45, 60)),
    ("talrain", _provider("Talrain", "maps/shattered_islands/world_9_69", "temples/elathiel.xml", 115, 60)),
    ("traba-jainkoaren", _provider("Traba Jainkoaren", "maps/shattered_islands/world_12_62", "temples/elathiel.xml", 115, 60)),
    ("gwenty", _provider("Gwenty", "maps/shattered_islands/world_4_53_-1", "quests/fort_sether_illness/quest.xml", 60, 60)),
    ("archbishop-theodorus-iii", _provider("Archbishop Theodorus III", "maps/shattered_islands/world_0_41", "temples/elathiel.xml", 68, 100)),
))


def provider_for(name, map_path):
    """Resolve one provider by its stable authored map and NPC identity."""

    map_path = "maps/" + str(map_path).lstrip("/")
    matches = [
        provider
        for provider in PROVIDERS.values()
        if provider.name == name and provider.map_path == map_path
    ]
    return matches[0] if len(matches) == 1 else None


def bounded_cost(raw, discount, minimum, maximum):
    """Apply the documented integer discount, rounding, and bounds."""

    cost = int(raw) * (100 - int(discount)) // 100
    cost = cost // ROUNDING_UNIT * ROUNDING_UNIT
    return min(int(maximum), max(int(minimum), cost))


def condition(count, difficulty, severity=0, evidence=()):
    """Create a normalized condition snapshot with a stable evidence digest."""

    count = max(0, int(count))
    difficulty = max(0, int(difficulty))
    severity = max(0, int(severity))
    payload = "\n".join(str(value) for value in evidence).encode("utf-8")
    fingerprint = hashlib.sha256(payload).hexdigest()[:16]
    return Condition(count, difficulty, severity, fingerprint)


def quote(service_name, patient_level, provider_rank, snapshot):
    """Return the exact bounded integer quote for one condition snapshot."""

    service = SERVICES[service_name]
    patient_level = max(1, int(patient_level))
    provider_rank = max(1, int(provider_rank))
    if snapshot.count <= 0:
        raise ValueError("no applicable condition")
    if snapshot.difficulty > provider_rank:
        raise ValueError("provider is incapable of reliably treating condition")

    free = (
        service.newcomer_essential
        and patient_level <= NEWCOMER_MAX_LEVEL
        and snapshot.difficulty <= NEWCOMER_MAX_DIFFICULTY
    )
    discount = min(
        MAX_CAPABILITY_DISCOUNT,
        max(0, (provider_rank - snapshot.difficulty) // 2),
    )
    if free:
        cost = 0
    else:
        raw = (
            service.base
            + patient_level * service.patient
            + snapshot.count * service.condition
            + snapshot.difficulty * service.difficulty
            + snapshot.severity * service.severity
        )
        cost = bounded_cost(
            raw, discount, service.minimum, service.maximum
        )

    token_fields = (
        service_name,
        cost,
        snapshot.count,
        snapshot.difficulty,
        snapshot.severity,
        provider_rank,
        snapshot.fingerprint,
    )
    token = ":".join(str(value) for value in token_fields)
    return Quote(
        service_name,
        cost,
        snapshot.count,
        snapshot.difficulty,
        snapshot.severity,
        provider_rank,
        free,
        discount,
        token,
    )


def treatment_progress(before, after):
    """Classify a synchronous pre/postcondition comparison."""

    before_burden = before.severity or before.count
    after_burden = after.severity or after.count
    if after_burden >= before_burden:
        return "failure"
    if after_burden == 0:
        return "full"
    return "partial"


def _archname(obj):
    arch = getattr(obj, "arch", None)
    return getattr(arch, "name", "")


def snapshot(service_name, objects, disease_type):
    """Inspect the immediate patient inventory for one spell's condition."""

    matches = []
    severity = 0
    for obj in objects:
        archname = _archname(obj)
        if service_name == "remove depletion":
            selected = archname == "depletion"
        elif service_name == "cure disease":
            selected = obj.type == disease_type
        elif service_name == "cure poison":
            selected = archname == "poisoning"
        elif service_name == "remove curse":
            selected = bool(obj.f_cursed)
        elif service_name == "remove damnation":
            selected = bool(obj.f_cursed or obj.f_damned)
        else:
            raise KeyError(service_name)
        if not selected:
            continue

        stats = tuple(
            int(getattr(obj, name))
            for name in ("Str", "Dex", "Con", "Int", "Pow")
        ) if service_name == "remove depletion" else ()
        if stats:
            severity += sum(abs(value) for value in stats if value < 0)
        matches.append((
            archname,
            getattr(obj, "name", ""),
            max(1, int(getattr(obj, "level", 1))),
            bool(getattr(obj, "f_cursed", False)),
            bool(getattr(obj, "f_damned", False)),
            stats,
        ))

    if not matches:
        return condition(0, 0)
    difficulty = max(match[2] for match in matches)
    if service_name == "remove depletion":
        difficulty = max(difficulty, severity * 5)
    return condition(
        len(matches), difficulty, severity,
        sorted(repr(match) for match in matches),
    )


def execute_treatment(preview, current, money, before, cast, resnapshot, pay):
    """Execute and settle one synchronous treatment without charging a no-op."""

    if current.token != preview.token:
        return Settlement("drift", 0, before)
    if money < current.cost:
        return Settlement("insufficient-funds", 0, before)
    cast()
    after = resnapshot()
    outcome = treatment_progress(before, after)
    if outcome == "failure":
        return Settlement(outcome, 0, after)
    if current.cost and not pay(current.cost):
        return Settlement("payment-failure", 0, after)
    return Settlement(outcome, current.cost, after)
