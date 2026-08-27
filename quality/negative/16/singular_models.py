

# Negatives: singular nouns that end in `s`. None of these is a plural, and a
# naive "ends with s" test would call all three violations.
class CanaryAnalysis(OrgScopedModel):
    class Meta:
        app_label = "example"


class CanaryAddress(OrgScopedModel):
    class Meta:
        app_label = "example"


class CanaryStatus(OrgScopedModel):
    class Meta:
        app_label = "example"
