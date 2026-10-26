"""The names of the things this app says happened."""

from __future__ import annotations

# golden: import begin
# golden: noun begin
WIDGET_CREATED = "example.widget.created"
# golden: import end
# golden: version move bulk history duplicate attach merge import begin
WIDGET_UPDATED = "example.widget.updated"
# golden: version move bulk history duplicate attach merge import end
WIDGET_DELETED = "example.widget.deleted"
# golden: noun end
# A press that changes nothing but `updated_at`: said on every press, a repeat included.
# golden: verb touch begin
WIDGET_TOUCHED = "example.widget.touched"
# golden: verb touch end
# A status moved one step (`Widget.STATUS_NEXT`); the payload is the row at its new status.
# golden: enum status begin
WIDGET_TRANSITIONED = "example.widget.transitioned"
# golden: enum status end

# golden: workflow onboard begin
# The one an app cannot emit from a request: an activity says it.
WIDGET_ONBOARDED = "example.widget.onboarded"
# golden: workflow onboard end

# golden: workflow remind begin
# Said by the reminder's activity once the row's moment arrives, never by a request.
WIDGET_REMINDED = "example.widget.reminded"
# golden: workflow remind end

# golden: webhook-in onboarding begin
# A signed onboarding delivery confirmed this widget; never said on a redelivery.
WIDGET_ONBOARDING_CONFIRMED = "example.widget.onboarding_confirmed"
# golden: webhook-in onboarding end

# Archive and restore: said only when the press CHANGED the row.
# golden: archive version move bulk history duplicate attach merge import begin
# golden: noun begin
WIDGET_ARCHIVED = "example.widget.archived"
WIDGET_RESTORED = "example.widget.restored"
# golden: noun end
# golden: archive version move bulk history duplicate attach merge import end
# golden: policy begin
WIDGET_POLICY_ARCHIVED = "example.widget_policy.archived"
WIDGET_POLICY_RESTORED = "example.widget_policy.restored"
# golden: policy end

# A widget re-homed at another node, or handed to another owner.
# golden: move bulk history duplicate attach merge import begin
WIDGET_MOVED = "example.widget.moved"
# golden: move bulk history duplicate attach merge import end

# A copy made from a widget: the payload is the COPY, and `duplicated_from_id`
# golden: duplicate attach merge import begin
WIDGET_DUPLICATED = "example.widget.duplicated"
# golden: duplicate attach merge import end

# Two widgets became one: the payload is the SURVIVOR, `loser_id` the one folded away.
# golden: merge import begin
WIDGET_MERGED = "example.widget.merged"
# golden: merge import end
