"""Rule 29's red leads with the remedy that fits the parameter, and names the ratchet second."""

# does-not-cover: the engine's unmeasured-class preface printed before a product app's findings.
# does-not-cover: whether a `str` parameter named `role` is in fact a job title — the reason says.

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from quality.checks.rule_29 import role_bound_assignment

ROOT = Path(__file__).resolve().parents[2]

SERVICE = """\
from apps.core.services import service


@service
def create_shift(*, tenant: object, actor: object, role: {annotation}) -> object:
    return Shift.objects.create(tenant=tenant, role=role)
"""


def _rule_29() -> dict[str, Any]:
    doc = yaml.safe_load((ROOT / "quality/rules.yaml").read_text())
    return next(r for r in doc["rules"] if str(r["id"]) == "29")


def _red(tmp_path: Path, annotation: str) -> str:
    """Rule 29's one finding over a copy holding `create_shift(role: <annotation>)`."""
    app = tmp_path / "apps" / "rosters"
    app.mkdir(parents=True)
    (app / "__init__.py").write_text("")
    (app / "apps.py").write_text("")
    (app / "services.py").write_text(SERVICE.format(annotation=annotation))
    (finding,) = role_bound_assignment(tmp_path, _rule_29()).findings
    return finding.msg


def test_the_valve_is_the_first_remedy(tmp_path: Path) -> None:
    message = _red(tmp_path, "str")
    lead = (
        "carry # role-bound: <reason> on the parameter when role is a plain field "
        "(a job title), or call the escalation wall"
    )
    assert lead in message
    assert "no bound against the actor" in message
    assert message.index(lead) < message.index("ratchet")


def test_a_typed_role_leads_with_the_wall(tmp_path: Path) -> None:
    message = _red(tmp_path, "Membership.Role")
    assert message.index("call the escalation wall") < message.index("# role-bound:")
    assert message.index("# role-bound:") < message.index("ratchet")
