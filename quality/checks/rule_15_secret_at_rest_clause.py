"""Rule 15's secret-at-rest clause."""

from __future__ import annotations

import re
from pathlib import Path

from quality.checks._hub import CheckResult, _exempt

# --- rule 15's secret-at-rest clause ------------------------------------------
#
# The plaintext-credential class, closed for the one field that had
# it. `WebhookEndpoint.secret` was a plain `CharField` in a tree where every
# sibling credential was already encrypted — the outbound signing secret sat in
# the clear beside `Connection.credentials` (EncryptedJSONField) and
# `SsoConnection.metadata` (the same). One field being wrong while its
# neighbours are right is what a rule is for: nobody decided it, it was just
# never noticed.
#
# THE POPULATION IS NAME-SHAPED, and the grammar is written out rather than
# gestured at, because a name set nobody can read is a name set nobody can argue
# with. `credentials` is in it deliberately: without it,
# `Connection.credentials` would be silent because the rule never LOOKED, and a
# negative that passes for the wrong reason is decoration.
_SECRET_FIELD = re.compile(
    r"^(secret|token|password|credentials|signing_key|api_key|private_key"
    r"|access_token|refresh_token|client_secret"
    r"|.*_secret|.*_token|.*_password|.*_credentials|.*_signing_key|.*_api_key"
    r"|.*_private_key)$"
)
# A digest is not a recoverable secret. Encrypting one would protect nothing and
# would break the unique lookup that authenticates every request — `key_hash`
# and `token_hash` are the tree's two, and both are right as they are. Excluded
# by construction rather than by two allow-list entries that would breed.
_DIGEST_FIELD = re.compile(r"_hash$")
# A secret-shaped name on a RELATION points at a row; it holds nothing.
_RELATION_FIELDS = ("ForeignKey", "OneToOneField", "ManyToManyField")


def secret_at_rest(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    for path, node in _model_classes(root):
        rel = path.relative_to(root).as_posix()
        for line, name, value in _field_assignments(node):
            call = _call_name(value)
            if not call.endswith("Field"):
                continue
            out.count("model_fields")
            short = call.rsplit(".", 1)[-1]
            if short in _RELATION_FIELDS:
                continue
            if _DIGEST_FIELD.search(name) or not _SECRET_FIELD.match(name):
                continue
            out.count("secret_fields")
            if "Encrypted" in short:
                out.count("encrypted_secrets")
                continue
            if _exempt(rule, rel, f"{node.name}.{name}"):
                out.count("secret_valves")
                continue
            out.hit(
                rel,
                line,
                f"{node.name}.{name} is a {short} — a secret-shaped field in the clear. "
                "Every sibling credential in this tree is encrypted at rest "
                "(core.fields.EncryptedCharField / EncryptedJSONField); a database dump, a "
                "replica, a backup and a traceback are four ways a plaintext one leaves. "
                "Use an encrypted field type. If this field is not really a secret, "
                "`# rule-15: <reason>` on its line is the counted, printed road for this "
                "one line; the rules.yaml allow-list is the heavier one and blesses the "
                "NAME for the whole template (rule 15)",
                klass="secrets",
            )
    return out


from quality.checks.rule_16_the_rest_of_the_grammar import (  # noqa: E402
    _call_name,
    _field_assignments,
    _model_classes,
)
