"""The platform's own tree through links, for a case that scaffolds a scratch noun onto it."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def product_labels() -> frozenset[str]:
    """The installed apps outside the platform's partition: the running tree's product apps."""
    from django.conf import settings

    from quality.partition import platform_apps

    platform = set(platform_apps())
    installed = {name.removeprefix("apps.") for name in settings.LOCAL_APPS}
    return frozenset(installed - platform)


def platform_tree(tmp_path: Path, namespace: str | None) -> Path:
    """The platform's tree through links, no product app linked, declaring `namespace`."""
    root = tmp_path / "tree"
    (root / "quality" / "local").mkdir(parents=True)
    for child in ROOT.iterdir():
        if child.name not in {"quality", "apps"}:
            (root / child.name).symlink_to(child)
    for child in (ROOT / "quality").iterdir():
        if child.name != "local":
            (root / "quality" / child.name).symlink_to(child)
    (root / "apps").mkdir()
    for child in (ROOT / "apps").iterdir():
        if child.name not in product_labels():
            (root / "apps" / child.name).symlink_to(child)
    if namespace is not None:
        (root / "quality/local/rules.yaml").write_text(f"rule_id_namespace: {namespace}\n")
    return root
