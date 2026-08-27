

class CanaryFlagged(OrgScopedModel):
    archived = models.BooleanField(default=False)  # planted: a bare adjective

    class Meta:
        app_label = "example"
