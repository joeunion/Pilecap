

class NegAllowListedVault(OrgScopedModel):
    """A plaintext secret that is silent BECAUSE somebody wrote the reason down.

    The statement's last clause — "or is allow-listed here with the reason" —
    is a valve, and until this fixture landed nothing had ever turned it. An
    allow-list no test exercises is a documented hope: the first product to
    lean on it is the one that finds out whether it works, live, on the day it
    is holding a field back.

    So this is the listed half. `signing_key` is a plain `CharField` — the rule
    looks straight at it, the name is in the grammar, the type is not encrypted
    — and the only thing standing between it and a finding is the rule 15
    exemption naming `NegAllowListedVault.signing_key`. Its twin,
    `quality/canary/15/unlisted_vault_secret.py`, is the same two field
    declarations under a class name the list does not carry, and it fires.

    One field apart, one list entry apart, opposite verdicts. That pair is what
    makes the valve load-bearing instead of advertised.
    """

    label = models.CharField(max_length=64)
    signing_key = models.CharField(max_length=255)
