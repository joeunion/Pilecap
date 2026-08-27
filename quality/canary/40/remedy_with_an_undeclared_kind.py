# CANARY (rule 40, the kind half): a destination in a kind nobody declared.
#
# `url:` is exactly the shape ADR core-5 refused — a remedy that promises a URL
# this template cannot know a product will serve, where every declared kind says
# where to LOOK without promising an address. A renderer that meets an unknown
# kind has a button with nowhere to go.
#
# It was `route:` until QB-R2, and the reason it is not any more is the reason
# this canary is worth reading: DECLARED `route:`, which names an operation
# by its `url_name` — the handle the ninja registry already keys on, so it
# promises no URL either and the objection never applied to it. The kinds live
# in `Remedy`'s own docstring; a seventh is added there, beside the others, and
# this rule follows it with no edit to `quality/`. That is also what makes this
# canary fragile in the good way: the day somebody declares `url:` it goes
# silent, and the gate says so.
_canary_url_remedy = Remedy("Open the settings page", "url:https://example.test/settings")
