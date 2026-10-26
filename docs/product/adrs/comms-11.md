# ADR comms-11

- **ADR comms-11 (SES at the edge the wall already built)** *(narrowed, not
  reopened, by ADR comms-12 (`comms-12.md`) — its decision sentence
  "SES via anymail" became "anymail is the seam"; its rejected list and
  trigger stand)* · context: the Email row says
  provider-in-production via the ESP edge; anymail is already the
  normalization layer (providers.py reads anymail's EventType/RejectReason;
  comms-9's hard/soft fork keys off it); example.invalid's warm-up clock is
  running; the wall's round-trip (bounce → suppress, hard-only) is proven
  so far against fixtures, never against a real provider · decision: SES
  via `django-anymail[amazon-ses]` (boto3 — the one new dependency); domain
  identity `example.invalid`, Easy DKIM, SPF on MAIL FROM `mail.example.invalid`,
  DMARC `p=none` at first observation moving to `p=quarantine` when reports
  are clean (the runbook owns the promotion; the warm-up doctrine: low
  volume, real engagement first); bounce/complaint events via SNS HTTPS
  subscription into the app's existing status-webhook door (the exact seam —
  anymail's tracking view or the connections
  receiver — confirmed at measure-first; SNS signature verification required either
  way); sandbox proves the round-trip with SES simulator addresses before
  production access lands · rejected: SES SMTP relay (no tracking webhooks
  — the wall goes blind), a third-party ESP (a second vendor signup per
  clone against the AWS standing posture), skipping DMARC until a product
  ships (the warm-up clock is the point of doing this now) · trigger to
  revisit: first product with marketing-volume sending (dedicated IP /
  MAIL FROM per product), or SES production access refused (escalate to
  owner with the case).
