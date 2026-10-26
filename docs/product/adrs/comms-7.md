# ADR comms-7

- **ADR comms-7 (consent re-checks per escalation step)** ·
  consent RE-CHECKS per escalation step — send_step runs the full wall at
  that step's send time; a suppressed step writes its suppressed Message
  and the interpreter proceeds without waiting. Rejected: snapshot at entry
  (mid-chain revocation overridden), consent in the workflow (rules 9/10).
  trigger to revisit: quiet-hours scheduling (defer-until-window) — named
  deferral.
