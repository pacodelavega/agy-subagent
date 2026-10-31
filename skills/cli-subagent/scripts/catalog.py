"""Dynamic zero-token model catalog with <1ms fingerprint cache and semantic tiering."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

from drivers import create_driver_registry
from drivers.base import BaseDriver
import state

CATALOG_TTL_SECONDS = 86400  # 24 hours
VERSION_RE = re.compile(r"(\d+)(?:[.\-](\d+))?")
EFFORT_SUFFIX_RE = re.compile(r"-(low|medium|high|xhigh|max)$")


def extract_version_key(slug: str) -> Tuple[int, int]:
    """Extract primary (major, minor) numeric version from a model slug for newest-first sorting."""
    # Strip trailing effort suffix and parameter sizes like 120b before parsing version
    cleaned = EFFORT_SUFFIX_RE.sub("", slug.lower())
    cleaned = re.sub(r"-\d+b\b", "", cleaned)
    matches = VERSION_RE.findall(cleaned)
    if not matches:
        return (0, 0)
    major_str, minor_str = matches[0]
    return (int(major_str), int(minor_str) if minor_str else 0)


def extract_effort_suffix(slug: str) -> Optional[str]:
    m = EFFORT_SUFFIX_RE.search(slug.lower())
    return m.group(1) if m else None


def compute_provider_fingerprint(
    provider: str,
    provider_cfg: Dict[str, Any],
    driver: BaseDriver,
) -> str:
    """Compute a <1ms local filesystem fingerprint for binary + native model caches."""
    parts: List[str] = []
    bin_path = driver.resolve_binary_path(provider_cfg)
    parts.append(f"bin:{state.file_fingerprint(bin_path) or 'none'}")
    for cache_path in driver.native_catalog_cache_paths(provider_cfg):
        parts.append(f"{cache_path.parent.name}/{cache_path.name}:{state.file_fingerprint(cache_path) or 'none'}")
    return "|".join(parts)


def classify_provider_models(provider: str, raw_models: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Classify discovered models into fast, workhorse, and frontier tiers without static model lists."""
    tiers: Dict[str, List[Tuple[Tuple[int, int, int, int], str]]] = {
        "fast": [],
        "workhorse": [],
        "frontier": [],
    }
    catalog_entries: Dict[str, Dict[str, Any]] = {}

    for item in raw_models:
        slug = str(item.get("slug") or "").strip()
        if not slug:
            continue
        desc = str(item.get("description") or slug).strip()
        s_low = slug.lower()
        s_tokens = set(re.split(r"[-_./]+", s_low))
        d_low = desc.lower()
        ver = extract_version_key(slug)
        eff = extract_effort_suffix(slug)

        # Skip redundant low/medium variants of frontier models to avoid cluttering queues
        tier: str
        family_prio = 5
        sub_rank = 5

        if provider == "agy":
            # In Antigravity, Flash/Lite are abundant/economical; non-Flash Gemini families
            # (Argon, Carbon, Pro, Ultra, etc.) and Claude Opus/Sonnet have scarce frontier pools.
            is_flash_or_lite = bool(s_tokens & {"flash", "lite", "mini", "nano", "fast"})
            is_open_oss = "oss" in s_tokens
            if is_flash_or_lite:
                family_prio = 10
                if eff in ("low", "medium") or "lite" in s_tokens:
                    tier = "fast"
                    sub_rank = 9 if eff == "medium" else 8
                else:
                    tier = "workhorse"
                    sub_rank = 10 if eff == "high" else 7
            elif is_open_oss:
                family_prio = 5
                tier = "workhorse"
                sub_rank = 4
            else:
                # Non-flash Gemini (Argon, Carbon, etc.) or Claude (Opus, Sonnet) -> frontier
                if eff in ("low", "medium"):
                    catalog_entries[slug] = {"description": desc, "tier": "frontier_variant", "version": list(ver)}
                    continue
                tier = "frontier"
                if s_low.startswith("gemini-"):
                    family_prio = 10
                    sub_rank = 10
                elif "opus" in s_tokens:
                    family_prio = 9
                    sub_rank = 9
                elif "sonnet" in s_tokens:
                    family_prio = 8
                    sub_rank = 8
                else:
                    family_prio = 6
                    sub_rank = 6

        elif provider == "codex":
            if "frontier" in d_low or "most demanding" in d_low or bool(s_tokens & {"astra", "pro", "max"}):
                tier = "frontier"
                sub_rank = 10
            elif "fast" in d_low or "affordable" in d_low or bool(s_tokens & {"luna", "mini", "nano", "reserve", "fast"}):
                tier = "fast"
                family_prio = 10 if "reserve" not in s_tokens else 5
                sub_rank = 9
            else:
                tier = "workhorse"
                prio = item.get("priority")
                sub_rank = 10 if prio == 1 else (9 if "sol" in s_tokens else 7)

        elif provider == "grok":
            if bool(s_tokens & {"mini", "fast", "lite"}):
                tier = "fast"
                sub_rank = 10
            elif "frontier" in d_low:
                tier = "frontier"
                sub_rank = 10
            else:
                tier = "workhorse"
                sub_rank = 10

        else:
            if "frontier" in d_low or bool(s_tokens & {"opus", "pro", "ultra", "max"}):
                tier = "frontier"
                sub_rank = 10
            elif "fast" in d_low or bool(s_tokens & {"haiku", "lite", "mini", "nano", "fast"}):
                tier = "fast"
                sub_rank = 10
            else:
                tier = "workhorse"
                sub_rank = 10

        sort_key = (family_prio, ver[0], ver[1], sub_rank)
        tiers[tier].append((sort_key, slug))
        catalog_entries[slug] = {
            "description": desc,
            "tier": tier,
            "version": [ver[0], ver[1]],
        }

    ordered_tiers: Dict[str, List[str]] = {}
    for t_name, bucket in tiers.items():
        bucket.sort(key=lambda pair: pair[0], reverse=True)
        ordered_tiers[t_name] = [slug for _, slug in bucket]

    # For Grok specifically: if multiple workhorse versions exist (e.g. grok-4.6 and grok-4.5),
    # place older standard versions into fast as well, and if frontier is empty, top version serves frontier.
    if provider == "grok":
        wh = ordered_tiers["workhorse"]
        if not ordered_tiers["fast"] and len(wh) >= 2:
            ordered_tiers["fast"] = wh[1:] + [wh[0]]
        elif not ordered_tiers["fast"] and wh:
            ordered_tiers["fast"] = list(wh)
        if not ordered_tiers["frontier"] and wh:
            ordered_tiers["frontier"] = [wh[0]]

    # Safe non-frontier fallbacks within economical tiers only (NEVER leak frontier into workhorse/fast!)
    if not ordered_tiers["fast"] and ordered_tiers["workhorse"]:
        ordered_tiers["fast"] = [ordered_tiers["workhorse"][-1]]
    if not ordered_tiers["workhorse"] and ordered_tiers["fast"]:
        ordered_tiers["workhorse"] = [ordered_tiers["fast"][0]]

    return {
        "tiers": ordered_tiers,
        "models": catalog_entries,
    }


def ensure_catalog(
    config: Dict[str, Any],
    *,
    drivers: Optional[Dict[str, BaseDriver]] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Return up-to-date catalog, refreshing ONLY providers whose <1ms fingerprint or 24h TTL expired."""
    registry = drivers or create_driver_registry()
    cached = state.load_catalog()
    cached_providers = cached.get("providers") if isinstance(cached.get("providers"), dict) else {}
    now = datetime.now(timezone.utc)
    changed = False
    new_providers: Dict[str, Any] = {}

    for prov_name, prov_cfg in config.get("providers", {}).items():
        if not isinstance(prov_cfg, dict) or not prov_cfg.get("enabled"):
            continue
        driver = registry.get(prov_name)
        if not driver:
            continue

        fp = compute_provider_fingerprint(prov_name, prov_cfg, driver)
        prev = cached_providers.get(prov_name) if isinstance(cached_providers, dict) else None

        is_fresh = False
        if not force and isinstance(prev, dict) and prev.get("fingerprint") == fp and prev.get("tiers"):
            fetched_dt = state.parse_iso(prev.get("fetched_at"))
            if fetched_dt and (now - fetched_dt).total_seconds() < CATALOG_TTL_SECONDS:
                is_fresh = True

        if is_fresh and prev is not None:
            new_providers[prov_name] = prev
            continue

        # Fingerprint changed or TTL expired -> refresh native models
        raw_models = driver.discover_native_models(prov_cfg)
        classified = classify_provider_models(prov_name, raw_models)
        # If CLI was temporarily unreachable and returned 0 models, retain previous known tiers if available
        if not raw_models and isinstance(prev, dict) and prev.get("tiers"):
            new_providers[prov_name] = {
                **prev,
                "fingerprint": fp,
                "fetched_at": state.utc_now_iso(),
            }
        else:
            new_providers[prov_name] = {
                "fingerprint": fp,
                "fetched_at": state.utc_now_iso(),
                "tiers": classified["tiers"],
                "models": classified["models"],
            }
        changed = True

    result = {
        "schema": state.SCHEMA_VERSION,
        "updated_at": cached.get("updated_at") if not changed and cached.get("updated_at") else state.utc_now_iso(),
        "providers": new_providers,
    }
    if changed or not state.catalog_path().is_file():
        state.save_catalog(result)
    return result
