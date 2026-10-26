# ADR comms-12

- **ADR comms-12 (anymail is the seam; the provider is the product's)**
  · context: comms-11 chose SES
  because the template would operate its own sender; the owner ruled the
  template never carries production traffic and a first consuming product
  already sends through Resend, verified for its own domain; the wall reads anymail's
  normalized events (`providers.py:368-400`), which are provider-agnostic
  by construction · decision: the template proves the mechanism
  `comms.send()` → anymail → a real provider → the bounce event back
  through the real receiver, once, against Resend; no provider SDK is
  added (boto3 not added); the provider a product uses is the product's
  setting (`EMAIL_BACKEND`), documented in the runbook as one line per
  supported anymail backend · rejected: SES for the template (an
  account-level review clock and a second vendor the first product will
  not use), a provider-abstraction layer of our own (anymail IS it),
  mail-body PHI enforcement (owner correction: not the platform's concern
  — refused as a rule, a canary or a design-agreement line) · trigger to
  revisit: a product whose provider anymail does not support, or a product
  that needs a BAA its provider will not sign (then that product chooses
  SES and its clocks start).
