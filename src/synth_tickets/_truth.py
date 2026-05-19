"""Hidden ground-truth scoring functions for synthetic support tickets.

These functions are *not* fed as features. They drive the labels
(`priority_actual`, `sla_breached`) so the model has a learnable signal
without label leakage. Keep them here so they can be unit-tested and
inspected, and so demos can honestly say "the labels are synthetic but
follow these rules".
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

PRIORITY_LEVELS = ("Low", "Medium", "High", "Critical")

# Issue categories that materially raise priority for an M365/SaaS shop.
_HIGH_IMPACT_CATEGORIES = {"Data loss", "Compliance", "Auth"}
_REGULATED_PRODUCTS = {"Purview", "Entra", "Contoso Confide", "Contoso Policies"}


@dataclass
class TicketContext:
    """Subset of ticket fields used by the truth functions.

    Kept narrow so callers can build it without depending on the full
    generator schema.
    """

    customer_tier: str  # Free / Standard / Premium / Enterprise
    issue_category: str
    product_area: str
    tenant_seat_count: int
    attached_logs: bool
    prior_tickets_30d: int
    agent_tier: str  # T1 / T2 / T3
    region: str  # NA / EMEA / APAC / LATAM
    created_weekday: int  # 0=Mon ... 6=Sun
    created_hour: int  # 0..23 in customer-local time


def priority_score(ctx: TicketContext, rng: random.Random) -> float:
    """Continuous score that drives bucketed priority. Higher = more urgent."""
    s = 0.0

    # Customer tier: paying customers get faster attention.
    s += {"Free": 0.0, "Standard": 1.0, "Premium": 2.0, "Enterprise": 3.0}[ctx.customer_tier]

    # Issue category dominates: data loss / auth / compliance -> always serious.
    if ctx.issue_category in _HIGH_IMPACT_CATEGORIES:
        s += 3.0
    elif ctx.issue_category in {"Permissions", "Sync"}:
        s += 1.0
    elif ctx.issue_category == "Billing":
        s -= 0.5

    # Regulated product surfaces slightly raise stakes.
    if ctx.product_area in _REGULATED_PRODUCTS:
        s += 1.0

    # Big tenants -> more blast radius.
    if ctx.tenant_seat_count > 10000:
        s += 2.0
    elif ctx.tenant_seat_count > 1000:
        s += 1.0

    # Repeat ticket within 30d signals an unresolved problem.
    if ctx.prior_tickets_30d >= 5:
        s += 1.5
    elif ctx.prior_tickets_30d >= 2:
        s += 0.5

    # Customers who attach diagnostic logs tend to file better-scoped, lower-noise tickets.
    if ctx.attached_logs:
        s -= 0.7

    # Gaussian noise keeps the model from being trivially perfect.
    s += rng.gauss(0.0, 0.9)
    return s


def bucket_priority(score: float) -> str:
    """Map a continuous priority score to one of PRIORITY_LEVELS."""
    if score >= 6.0:
        return "Critical"
    if score >= 4.0:
        return "High"
    if score >= 2.0:
        return "Medium"
    return "Low"


def sla_breach_probability(ctx: TicketContext, priority_actual: str) -> float:
    """Probability that this ticket misses its SLA, in [0, 1].

    Drivers: priority/agent mismatch, after-hours creation, regional
    follow-the-sun gaps, and repeat-customer fatigue.
    """
    # Base rate roughly mirrors a real well-run support org:
    # majority hit SLA; a stubborn tail does not.
    base = {"Low": 0.05, "Medium": 0.10, "High": 0.20, "Critical": 0.30}[priority_actual]

    # Agent tier mismatch: a T1 handling a Critical is asking for a breach.
    tier_gap = {
        ("Critical", "T1"): 0.35, ("Critical", "T2"): 0.10,
        ("High", "T1"): 0.15,
    }.get((priority_actual, ctx.agent_tier), 0.0)

    # After-hours creation in regions without 24/7 coverage.
    after_hours = ctx.created_hour < 7 or ctx.created_hour >= 19
    weekend = ctx.created_weekday >= 5
    when_penalty = 0.0
    if after_hours:
        when_penalty += 0.10
    if weekend:
        when_penalty += 0.10
    # APAC tickets tend to be created when other regions are asleep.
    if ctx.region == "APAC" and after_hours:
        when_penalty += 0.05

    # Repeat-customer fatigue.
    repeat_penalty = 0.05 if ctx.prior_tickets_30d >= 3 else 0.0

    # Squash to [0, 1] with a logistic so penalties don't blow past 100%.
    raw = base + tier_gap + when_penalty + repeat_penalty
    return 1.0 / (1.0 + math.exp(-(raw - 0.5) * 4))
