

# NEGATIVE (rule 17): `RefusalOut.errors` re-typed from a map of string lists to a
# record whose every key is required and a string list — a narrowing. Must stay silent.
class RefusalErrorsOut(Schema):
    name: list[str]


class RefusalOut(Schema):
    model_config = ConfigDict(extra="allow")

    detail: str
    code: str
    errors: RefusalErrorsOut
    remedies: list[RefusalRemedyOut] = Field(default_factory=list)
