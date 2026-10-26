

# CANARY (rule 17): `RefusalOut.errors` re-typed to a record whose value is no
# string list — the published shape moved, so the re-type is the finding.
class RefusalErrorsOut(Schema):
    name: list[int]


class RefusalOut(Schema):
    model_config = ConfigDict(extra="allow")

    detail: str
    code: str
    errors: RefusalErrorsOut
    remedies: list[RefusalRemedyOut] = Field(default_factory=list)
