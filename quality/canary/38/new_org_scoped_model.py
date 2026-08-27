

# CANARY SUPPORT (rule 38): the org-scoped model `SprocketOut` claims to report.
# Planted into the real models.py so `org_scoped_model_names`' transitive walk
# finds it the same way it finds Widget.
class Sprocket(OrgScopedModel):
    name = models.CharField(max_length=64)
