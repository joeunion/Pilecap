# ADR events-5

- **ADR events-5 (outbound targets refused by address class)** · an
  outbound webhook target is refused by the class of address it names or
  resolves to — not https, a local name, unresolvable, unspecified,
  loopback, link-local, multicast, private, reserved, not globally routable —
  at the door (with DNS), the service (literal only: no I/O inside its
  transaction) and the delivery (with DNS, before the POST; a refusal is a
  failed, non-retryable attempt; redirects are never followed);
  `apps/events/targets.py` · rejected: an allow-list of hosts (a hand list
  of an open set), grandfathering existing rows (a tenant admin's old row is
  tomorrow's metadata read) · trigger to revisit: a product needs a webhook
  to a private VPC peer — then `WEBHOOK_PRIVATE_TARGETS_ALLOWED` per
  deployment is the valve already present, and a per-endpoint allow is a new
  row.
