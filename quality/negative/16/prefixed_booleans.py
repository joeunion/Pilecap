

# Negatives: both prefixes, and a non-boolean field whose name is a bare
# adjective — the check must read the field TYPE, not the name.
class CanaryGizmo(OrgScopedModel):
    is_enabled = models.BooleanField(default=False)
    has_quota = models.BooleanField(default=True)
    archived_at = models.DateTimeField(null=True)

    class Meta:
        app_label = "example"
