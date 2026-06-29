"""Compatibility helpers for old and generated world JSON shapes."""

from __future__ import annotations

from typing import Any


def as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def geography_of(world: dict) -> dict:
    return as_dict(as_dict(world).get("geography"))


def regions_of(world: dict) -> list[dict]:
    """Return regions as a list regardless of storage shape.

    New generated worlds often use `{region_id: {...}}`; imported/legacy worlds
    may use `[{name, description, ...}]`.  Agent prompt builders need one safe
    view over both.
    """
    regions = geography_of(world).get("regions", {})
    if isinstance(regions, dict):
        result = []
        for region_id, region in regions.items():
            if isinstance(region, dict):
                item = {"id": region_id, **region}
                item.setdefault("name", region_id)
                result.append(item)
        return result
    if isinstance(regions, list):
        return [region for region in regions if isinstance(region, dict)]
    return []


def current_region_id(world: dict) -> str:
    geography = geography_of(world)
    current = geography.get("current_region") or geography.get("current_region_id") or ""
    if current:
        return str(current)
    regions = regions_of(world)
    if not regions:
        return ""
    first = regions[0]
    return str(first.get("id") or first.get("name") or "")


def current_region_info(world: dict) -> dict:
    current = current_region_id(world)
    regions = regions_of(world)
    if not regions:
        return {}
    for region in regions:
        if current in {str(region.get("id", "")), str(region.get("name", ""))}:
            return region
    return regions[0]


def landmark_names(region: dict, limit: int = 5) -> list[str]:
    names = []
    for landmark in as_list(as_dict(region).get("landmarks"))[:limit]:
        if isinstance(landmark, dict):
            names.append(str(landmark.get("name", "")))
        elif isinstance(landmark, (str, int, float)):
            names.append(str(landmark))
    return [name for name in names if name]
