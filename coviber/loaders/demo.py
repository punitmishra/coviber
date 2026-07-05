"""Demo loader — synthetic, non-proprietary data so CoViber runs with zero setup.

Generates a small, realistic cross-platform stream for a fictional company
("Acme Robotics") with obvious urgency signals, so `coviber demo` shows the
graph, triage queue, and search working end-to-end offline.
"""
from __future__ import annotations

from typing import Iterable

from ..record import Record
from . import register
from .base import Loader

# A fictional company. Any resemblance to real orgs/people is coincidental.
_DATA = [
    dict(source="email", from_name="Grace Hopper", recipient="you", channel="inbox",
         subject="Re: Falcon launch sign-off needed", unread=True,
         text="Can you review and approve the Falcon release plan today? We're blocked on your sign-off."),
    dict(source="slack", from_name="Linus Vega", recipient="you", channel="dm",
         subject="DM: Linus Vega",
         text="@you the Orbit API is returning 500s in staging — is this expected after your change?"),
    dict(source="github", from_name="Margaret Chen", channel="apex/orbit-service",
         subject="PR #482: add retry + backoff to Orbit client", url="https://example.com/pr/482",
         text="Requesting your review — this touches the Falcon integration path."),
    dict(source="tracker", from_name="Ada Byron", channel="mentions",
         subject="ATLAS-1290 Blocked: waiting on your schema decision",
         text="Need a decision on the Atlas tenant schema before we can proceed. Deadline Friday."),
    dict(source="slack", from_name="acme-ci-bot", recipient="you", channel="#builds",
         subject="Build passed", text="main build green ✅ nothing to do here"),
    dict(source="email", from_name="newsletter@acme.com", channel="inbox",
         subject="[Weekly Digest] Acme Robotics news",
         text="FYI: this week's company newsletter. No action needed."),
    dict(source="teams", from_name="Grace Hopper", channel="Falcon Standup",
         subject="Meeting: Falcon go/no-go",
         text="Reminder: Falcon go/no-go at 3pm. Please bring the risk assessment."),
    dict(source="github", from_name="Linus Vega", channel="apex/atlas",
         subject="PR #77: Atlas provisioning sidecar", url="https://example.com/pr/77",
         text="Draft — early feedback welcome on the provisioning approach."),
    dict(source="email", from_name="Ada Byron", recipient="you", channel="inbox", unread=True,
         subject="Question about the Orbit embedding router",
         text="Quick question — should the embedding router fall back to CPU when the GPU pool is saturated?"),
    dict(source="tracker", from_name="Margaret Chen", channel="mentions",
         subject="ORBIT-908 Review: reranker eval results",
         text="Posted the reranker A/B numbers. Can you confirm we ship config B?"),
    dict(source="slack", from_name="Grace Hopper", recipient="you", channel="dm",
         subject="DM: Grace Hopper",
         text="Thanks for the Falcon help earlier — all good now, no reply needed."),
    dict(source="email", from_name="security-alerts@acme.com", channel="inbox",
         subject="[ALERT] Dependency advisory for atlas-service",
         text="A new advisory affects atlas-service. Review and patch."),
    # A few messages you authored — lets the persona engine learn your voice (from_name == "you").
    dict(source="email", from_name="you", recipient="Grace Hopper", channel="sent",
         subject="Re: Falcon launch sign-off",
         text="Hi Grace, reviewed the plan — looks good to ship. One ask: let's gate the rollout on the canary metrics. Thanks, "),
    dict(source="slack", from_name="you", recipient="Linus Vega", channel="sent",
         subject="Re: Orbit 500s",
         text="Thanks for flagging — looking now. Can you drop the trace id? Will patch today."),
    dict(source="github", from_name="you", recipient="Margaret Chen", channel="sent",
         subject="Re: PR #482",
         text="Nice approach on the backoff. Please add a test for the jittered retry path, then good to merge."),
]


@register("demo")
class DemoLoader(Loader):
    """No config needed. Yields a fixed synthetic cross-platform stream."""

    def load(self) -> Iterable[Record]:
        for row in _DATA:
            yield Record(**row)
