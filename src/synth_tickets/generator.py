"""Faker-based generator for synthetic Contoso / M365 support tickets.

Public API: `generate_tickets(n, seed=42) -> pandas.DataFrame`.

Schema (16 cols, deliberately demoable):
    ticket_id, created_at, tenant_id, tenant_seat_count, customer_tier,
    product_area, issue_category, channel, region, language,
    priority_reported, attached_logs, prior_tickets_30d, agent_tier,
    priority_actual (target #1), sla_breached (target #2)

The two label columns are computed from `_truth.py` so the model has a
real, learnable signal without leakage.
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from faker import Faker

from ._truth import (
    PRIORITY_LEVELS,
    TicketContext,
    bucket_priority,
    priority_score,
    sla_breach_probability,
)

_PRODUCT_AREAS = [
    "SharePoint", "Teams", "Exchange", "OneDrive",
    "Purview", "Entra",
    "Contoso Cloud Backup", "Contoso Confide", "Contoso Policies",
]
_ISSUE_CATEGORIES = [
    "Auth", "Permissions", "Sync", "Performance",
    "Data loss", "Compliance", "Migration", "Billing",
]
_CHANNELS = ["Portal", "Email", "Phone", "Teams", "Partner"]
_REGIONS = ["NA", "EMEA", "APAC", "LATAM"]
_LANGUAGES = ["en", "de", "fr", "ja", "es", "pt"]
_CUSTOMER_TIERS = ["Free", "Standard", "Premium", "Enterprise"]
_TIER_WEIGHTS = [0.10, 0.45, 0.30, 0.15]
_AGENT_TIERS = ["T1", "T2", "T3"]
_AGENT_TIER_WEIGHTS = [0.55, 0.30, 0.15]


def _log_normal_seats(rng: random.Random) -> int:
    """Tenant size: long-tail from ~25 seats to ~50k."""
    val = int(np.exp(rng.gauss(5.5, 1.4)))
    return max(25, min(val, 50_000))


def _weighted_choice(rng: random.Random, items: list[str], weights: list[float]) -> str:
    return rng.choices(items, weights=weights, k=1)[0]


def _make_tenant_pool(fake: Faker, n_tenants: int = 500) -> list[tuple[str, str]]:
    """Pre-generate a stable pool of (tenant_id, region) so tenants repeat realistically."""
    pool: list[tuple[str, str]] = []
    for _ in range(n_tenants):
        tid = "tnt_" + fake.bothify(text="????####").lower()
        region = fake.random_element(_REGIONS)
        pool.append((tid, region))
    return pool


def generate_tickets(n: int = 200_000, seed: int = 42) -> pd.DataFrame:
    """Generate `n` synthetic support tickets with two ML-ready label columns."""
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)
    fake = Faker()
    Faker.seed(seed)

    tenant_pool = _make_tenant_pool(fake, n_tenants=500)
    # Zipfian-ish weights: a few big tenants generate a lot of the volume.
    tenant_weights = np_rng.zipf(a=1.6, size=len(tenant_pool)).astype(float)
    tenant_weights = tenant_weights / tenant_weights.sum()
    tenant_seat_map = {tid: _log_normal_seats(rng) for tid, _ in tenant_pool}

    # Spread tickets across the last 18 months with a weekday bias.
    end = datetime(2026, 5, 1)
    start = end - timedelta(days=18 * 30)
    span_seconds = int((end - start).total_seconds())

    rows: list[dict] = []
    tenant_ticket_history: dict[str, list[datetime]] = {tid: [] for tid, _ in tenant_pool}

    for _ in range(n):
        # Pick tenant with weighted probability.
        tid_idx = np_rng.choice(len(tenant_pool), p=tenant_weights)
        tenant_id, region = tenant_pool[tid_idx]
        seats = tenant_seat_map[tenant_id]

        # Created_at: bias toward weekdays and business hours, but keep some weekend traffic.
        created_at = start + timedelta(seconds=rng.randint(0, span_seconds))
        if created_at.weekday() >= 5 and rng.random() < 0.6:
            # 60% of weekend draws get re-rolled to a weekday
            created_at -= timedelta(days=rng.randint(1, 2))
        if not (7 <= created_at.hour < 19) and rng.random() < 0.5:
            created_at = created_at.replace(hour=rng.randint(8, 17))

        # Prior tickets in the trailing 30 days for this tenant.
        cutoff = created_at - timedelta(days=30)
        prior = sum(1 for t in tenant_ticket_history[tenant_id] if t >= cutoff)
        tenant_ticket_history[tenant_id].append(created_at)

        customer_tier = _weighted_choice(rng, _CUSTOMER_TIERS, _TIER_WEIGHTS)
        product_area = rng.choice(_PRODUCT_AREAS)
        issue_category = rng.choice(_ISSUE_CATEGORIES)
        channel = rng.choice(_CHANNELS)
        language = rng.choice(_LANGUAGES)
        attached_logs = rng.random() < 0.35
        priority_reported = rng.choices(
            list(PRIORITY_LEVELS), weights=[0.35, 0.40, 0.20, 0.05], k=1
        )[0]
        agent_tier = _weighted_choice(rng, _AGENT_TIERS, _AGENT_TIER_WEIGHTS)

        ctx = TicketContext(
            customer_tier=customer_tier,
            issue_category=issue_category,
            product_area=product_area,
            tenant_seat_count=seats,
            attached_logs=attached_logs,
            prior_tickets_30d=prior,
            agent_tier=agent_tier,
            region=region,
            created_weekday=created_at.weekday(),
            created_hour=created_at.hour,
        )
        score = priority_score(ctx, rng)
        priority_actual = bucket_priority(score)
        breach_p = sla_breach_probability(ctx, priority_actual)
        sla_breached = rng.random() < breach_p

        rows.append({
            "ticket_id": str(uuid.UUID(int=rng.getrandbits(128))),
            "created_at": created_at,
            "tenant_id": tenant_id,
            "tenant_seat_count": seats,
            "customer_tier": customer_tier,
            "product_area": product_area,
            "issue_category": issue_category,
            "channel": channel,
            "region": region,
            "language": language,
            "priority_reported": priority_reported,
            "attached_logs": attached_logs,
            "prior_tickets_30d": prior,
            "agent_tier": agent_tier,
            "priority_actual": priority_actual,
            "sla_breached": sla_breached,
        })

    df = pd.DataFrame(rows)

    # Inject realistic missingness on a couple of optional fields.
    miss_mask = np_rng.random(len(df)) < 0.04
    df.loc[miss_mask, "language"] = None
    miss_mask = np_rng.random(len(df)) < 0.07
    df.loc[miss_mask, "prior_tickets_30d"] = None

    return df
