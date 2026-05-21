from __future__ import annotations

from dataclasses import dataclass


_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "embedded_signup_session_created": {"oauth_code_received", "phone_registration_queued", "failed"},
    "oauth_code_received": {"phone_registration_queued", "failed"},
    "phone_registration_queued": {"phone_registration_pending", "phone_registration_verified", "phone_registration_failed"},
    "phone_registration_pending": {"phone_registration_pending", "phone_registration_verified", "phone_registration_failed"},
    "phone_registration_verified": set(),
    "phone_registration_failed": set(),
    "failed": set(),
}


@dataclass
class OnboardingStateTransitionResult:
    status: str
    current_step: str
    compensating_action_required: bool


def transition_onboarding_state(current_step: str | None, next_step: str) -> OnboardingStateTransitionResult:
    source = str(current_step or "embedded_signup_session_created").strip().lower()
    target = str(next_step or "").strip().lower()
    if not target:
        raise ValueError("next onboarding step must be provided")
    allowed = _ALLOWED_TRANSITIONS.get(source)
    if allowed is None:
        raise ValueError(f"unknown onboarding step: {source}")
    if target not in allowed and target != source:
        raise ValueError(f"invalid onboarding transition: {source} -> {target}")
    if target == "phone_registration_verified":
        return OnboardingStateTransitionResult(
            status="completed",
            current_step=target,
            compensating_action_required=False,
        )
    if target in {"phone_registration_failed", "failed"}:
        return OnboardingStateTransitionResult(
            status="failed",
            current_step=target,
            compensating_action_required=True,
        )
    return OnboardingStateTransitionResult(
        status="pending",
        current_step=target,
        compensating_action_required=False,
    )

