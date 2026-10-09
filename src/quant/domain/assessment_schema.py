"""D1: fixed assessment.json field contract (lightweight; pandera optional later)."""
from __future__ import annotations

REQUIRED_TOP = ("conclusion", "checks")


def validate_assessment(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("assessment must be a dict")
    for key in REQUIRED_TOP:
        if key not in payload:
            raise ValueError(f"assessment missing {key}")
    if payload["conclusion"] not in ("PAPER_CANDIDATE", "RESEARCH_ONLY", "REJECTED"):
        raise ValueError(f"unknown conclusion: {payload['conclusion']}")
    checks = payload.get("checks")
    if not isinstance(checks, dict):
        raise ValueError("assessment.checks must be a dict")
    return payload
