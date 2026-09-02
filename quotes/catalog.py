"""Plastics-processing equipment knowledge base."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_key(text: str) -> str:
    return _NON_ALNUM.sub("", (text or "").lower())


@dataclass(frozen=True)
class EquipmentSpec:
    sku: str
    name: str
    brand: str
    category: str
    function: str
    size: float | None = None
    aliases: tuple[str, ...] = field(default_factory=tuple)

    def keys(self) -> tuple[str, ...]:
        raw = (self.sku, self.name, *self.aliases)
        keys = []
        seen: set[str] = set()
        for item in raw:
            key = normalize_key(item)
            if key and key not in seen:
                seen.add(key)
                keys.append(key)
        return tuple(keys)


VENDORS: tuple[str, ...] = (
    "Piovan",
    "Maguire",
    "Conair",
    "Matsui",
    "Wittmann",
    "Motan",
    "Yushin",
    "Sepro",
    "Star",
)

CATEGORIES: tuple[tuple[str, str], ...] = (
    ("Dryers", "drying"),
    ("Hoppers", "storage"),
    ("Blenders", "blending"),
    ("Loaders", "resin handling"),
    ("Receivers", "resin handling"),
    ("Controls", "controls"),
    ("Robots", "robotics"),
    ("Instrumentation", "instrumentation"),
    ("Services", "services"),
    ("Options", "options"),
)

EQUIPMENT: tuple[EquipmentSpec, ...] = (
    EquipmentSpec(
        "GMP180",
        "Piovan GMP 180 Dryer",
        "Piovan",
        "Dryers",
        "drying",
        180,
        ("GMP 180", "GMP-180", "GMP180 Dryer", "Drying Unit GMP-180", "Drying Unit GMP180"),
    ),
    EquipmentSpec(
        "GMP250",
        "Piovan GMP 250 Dryer",
        "Piovan",
        "Dryers",
        "drying",
        250,
        ("GMP 250", "GMP-250", "GMP250 Dryer", "Drying Unit GMP-250"),
    ),
    EquipmentSpec(
        "PTUN2500",
        "Piovan PTUN 2500 Drying Hopper",
        "Piovan",
        "Hoppers",
        "storage",
        2500,
        ("PTUN 2500", "PTUN-2500", "PTUN2500 hopper", "drying hopper PTUN2500"),
    ),
    EquipmentSpec(
        "PTUN2000",
        "Piovan PTUN 2000 Drying Hopper",
        "Piovan",
        "Hoppers",
        "storage",
        2000,
        ("PTUN 2000", "PTUN-2000", "PTUN2000 hopper"),
    ),
    EquipmentSpec(
        "WSB240",
        "Maguire WSB 240 Blender",
        "Maguire",
        "Blenders",
        "blending",
        240,
        ("WSB 240", "WSB-240", "WSB240 blender"),
    ),
    EquipmentSpec(
        "TPA",
        "Conair TrueFeed loader",
        "Conair",
        "Loaders",
        "resin handling",
        None,
        ("TrueFeed", "loader controls", "vacuum loader"),
    ),
    EquipmentSpec(
        "VACUUMRECEIVER",
        "Vacuum receiver",
        "Piovan",
        "Receivers",
        "resin handling",
        None,
        ("vacuum receiver", "receiver"),
    ),
    EquipmentSpec(
        "LOADERCONTROLS",
        "Loader controls",
        "Piovan",
        "Controls",
        "controls",
        None,
        ("loader controls", "loader control"),
    ),
    EquipmentSpec(
        "DEWPOINT",
        "Dew point sensor",
        "Piovan",
        "Instrumentation",
        "instrumentation",
        None,
        ("dew point sensor", "dewpoint sensor", "dew-point sensor"),
    ),
    EquipmentSpec(
        "INSTALLATION",
        "Installation",
        "Services",
        "Services",
        "installation",
        None,
        ("installation", "install"),
    ),
    EquipmentSpec(
        "STARTUP",
        "Start-up support",
        "Services",
        "Services",
        "start-up support",
        None,
        ("start-up support", "startup support", "start up support", "commissioning"),
    ),
    EquipmentSpec(
        "ELECTRICAL",
        "Electrical hookup",
        "Services",
        "Services",
        "electrical hookup",
        None,
        ("electrical hookup", "electrical"),
    ),
    EquipmentSpec(
        "INSULATION",
        "Hopper insulation",
        "Options",
        "Options",
        "hopper insulation",
        None,
        ("hopper insulation", "insulation"),
    ),
    EquipmentSpec(
        "LOADER",
        "Loader",
        "Piovan",
        "Loaders",
        "resin handling",
        None,
        ("loader", "loaders"),
    ),
)

FUNCTION_LABELS = {
    "drying": "drying",
    "storage": "storage",
    "resin handling": "resin handling",
    "blending": "blending",
    "controls": "controls",
    "instrumentation": "instrumentation",
    "installation": "installation",
    "start-up support": "start-up support",
    "electrical hookup": "electrical hookup",
    "hopper insulation": "hopper insulation",
    "robotics": "robotics",
    "options": "options",
    "services": "services",
}


def lookup_equipment(text: str) -> EquipmentSpec | None:
    blob = normalize_key(text)
    if not blob:
        return None
    best: EquipmentSpec | None = None
    best_len = 0
    for spec in EQUIPMENT:
        for key in spec.keys():
            if key and key in blob and len(key) >= best_len:
                best = spec
                best_len = len(key)
    return best


def lookup_vendor(text: str) -> str | None:
    blob = text or ""
    for vendor in VENDORS:
        if re.search(rf"\b{re.escape(vendor)}\b", blob, re.I):
            return vendor
    return None
