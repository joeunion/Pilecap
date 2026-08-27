

# NEGATIVE (rule 35): a join to a lookup table is a planner doing its job, not
# a finding — M2's `assert_no_seq_scan_on` lesson, promoted into the rule's
# grammar: a clause names the SUBJECT table and only that table, so pulling
# the tenant row alongside the endpoints must stay silent.
#
# Its own shape self-test (c)): the marker below says the fixture is
# planted, and the plans for this path are then required to carry a scan of
# `core_tenant` — the joined table this exempts. Without that, "silent" could
# mean the `select_related` never reached the plan at all.
#
# n107-plan-shape-marker: join-to-a-lookup-table
_negative_original_endpoints_for = endpoints_for


def endpoints_for(*, tenant, name):  # noqa: F811
    if tenant is None:
        return []
    endpoints = WebhookEndpoint.objects.for_tenant(tenant).select_related("tenant")
    return [endpoint for endpoint in endpoints if endpoint.wants(name)]
