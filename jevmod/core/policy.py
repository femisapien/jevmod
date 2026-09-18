"""Policy: turn a Verdict (probabilities) into a Decision (what to do), per tenant. Pure code, offline-testable."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..judge import CATEGORIES, Verdict

ACTIONS = ("off", "flag", "delete", "timeout")  # ordered by severity
DEFAULT_THRESHOLDS = {
    "spam": 0.85,
    "scam": 0.75,
    "harassment": 0.75,
    "nsfw": 0.8,
    "offtopic": 0.9,
    "selfharm": 0.8,
    "doxxing": 0.8,
    "minors": 0.7,
    "ai_generated": 0.85,  # experimental, see benchmark/ai_detect/REPORT.md
}
# selfharm is flag-only by design: moderators should reach out, not punish. doxxing/minors flag by default;
# communities that want automatic removal set delete/timeout explicitly.
EXPERIMENTAL = ("ai_generated",)  # never moved by the feedback loop until measured on real traffic
DEFAULT_ACTIONS = {
    "spam": "flag",
    "scam": "flag",
    "harassment": "flag",
    "nsfw": "flag",
    "offtopic": "off",
    "selfharm": "flag",
    "doxxing": "flag",
    "minors": "flag",
    "ai_generated": "off",  # opt-in: precision falls to about 0.2 at a realistic base rate
}
RULE_THRESHOLD = 0.8
POLICY_VERSION = 1


@dataclass
class Policy:
    thresholds: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_THRESHOLDS))
    actions: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_ACTIONS))
    rules: dict[str, str] = field(default_factory=dict)  # name -> natural-language rule
    rule_actions: dict[str, str] = field(default_factory=dict)  # name -> action (default flag)
    rule_thresholds: dict[str, float] = field(default_factory=dict)
    timeout_minutes: int = 10

    def enabled_categories(self) -> list[str]:
        return [c for c in CATEGORIES if self.actions.get(c, "off") != "off"]

    def active(self) -> bool:
        return bool(self.enabled_categories() or self.rules)

    def set_category(self, category: str, action: str, threshold: float | None = None) -> None:
        if category not in CATEGORIES:
            raise ValueError(f"unknown category {category!r}; one of {', '.join(CATEGORIES)}")
        if action not in ACTIONS:
            raise ValueError(f"unknown action {action!r}; one of {', '.join(ACTIONS)}")
        if category in EXPERIMENTAL and action not in ("off", "flag"):
            raise ValueError(
                f"{category} is experimental and can only be off or flag: its precision on a real community's "
                "traffic is too low to remove a message or time a member out"
            )
        self.actions[category] = action
        if threshold is not None:
            self.thresholds[category] = _clamp(threshold)

    def set_rule(self, name: str, text: str | None, action: str = "flag", threshold: float | None = None) -> None:
        name = name.strip().lower().replace(" ", "_")[:30]
        if text is None or not text.strip():
            self.rules.pop(name, None)
            self.rule_actions.pop(name, None)
            self.rule_thresholds.pop(name, None)
            return
        if len(self.rules) >= 5 and name not in self.rules:
            raise ValueError("up to 5 custom rules")
        if action not in ACTIONS:
            raise ValueError(f"unknown action {action!r}")
        self.rules[name] = text.strip()[:200]
        self.rule_actions[name] = action
        if threshold is not None:
            self.rule_thresholds[name] = _clamp(threshold)

    def nudge(self, category: str, delta: float = 0.03) -> float:
        """False-positive feedback: raise that category's threshold a notch.

        Experimental categories are not moved: their error rate has not been measured on a real community's
        traffic, so a handful of reactions would move the line on noise."""
        if category in EXPERIMENTAL:
            return self.thresholds.get(category, DEFAULT_THRESHOLDS.get(category, 0.9))
        if category.startswith("rule:"):
            name = category[5:]
            cur = self.rule_thresholds.get(name, RULE_THRESHOLD)
            self.rule_thresholds[name] = _clamp(cur + delta)
            return self.rule_thresholds[name]
        cur = self.thresholds.get(category, 0.9)
        self.thresholds[category] = _clamp(cur + delta)
        return self.thresholds[category]

    def to_dict(self) -> dict[str, Any]:
        return {
            "thresholds": self.thresholds,
            "actions": self.actions,
            "rules": self.rules,
            "rule_actions": self.rule_actions,
            "rule_thresholds": self.rule_thresholds,
            "timeout_minutes": self.timeout_minutes,
            "version": POLICY_VERSION,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Policy:
        p = cls()
        for k in ("thresholds", "actions", "rules", "rule_actions", "rule_thresholds"):
            if isinstance(d.get(k), dict):
                getattr(p, k).update(d[k])
        if "timeout_minutes" in d:
            p.timeout_minutes = int(d["timeout_minutes"])
        return p


@dataclass
class Decision:
    message_id: str
    action: str  # "none" | "flag" | "delete" | "timeout"
    category: str | None  # winning category or "rule:<name>"
    probability: float
    scores: dict[str, float]  # everything Jev returned, for the audit log
    judged: bool
    reason: str  # "jev" | "cache" | pre-filter reason | "quota" | "error_open"
    policy_version: int = POLICY_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "action": self.action,
            "category": self.category,
            "probability": round(self.probability, 4),
            "scores": {k: round(v, 4) for k, v in self.scores.items()},
            "judged": self.judged,
            "reason": self.reason,
            "policy_version": self.policy_version,
        }


def decide(policy: Policy, v: Verdict) -> Decision:
    """The most severe action whose threshold is crossed wins; ties go to the higher probability."""
    scores = {**v.scores, **{f"rule:{n}": p for n, p in v.custom.items()}}
    if not v.judged:
        return Decision(v.message_id, "none", None, 0.0, scores, False, v.reason)
    hits: list[tuple[str, float, str]] = []
    for c, p in v.scores.items():
        action = policy.actions.get(c, "off")
        if action != "off" and p >= policy.thresholds.get(c, 1.0):
            hits.append((c, p, action))
    for n, p in v.custom.items():
        action = policy.rule_actions.get(n, "flag")
        if action != "off" and p >= policy.rule_thresholds.get(n, RULE_THRESHOLD):
            hits.append((f"rule:{n}", p, action))
    if not hits:
        return Decision(v.message_id, "none", None, 0.0, scores, True, v.reason)
    category, p, action = max(hits, key=lambda h: (ACTIONS.index(h[2]), h[1]))
    return Decision(v.message_id, action, category, p, scores, True, v.reason)


def _clamp(x: float) -> float:
    return max(0.5, min(0.99, round(float(x), 2)))
