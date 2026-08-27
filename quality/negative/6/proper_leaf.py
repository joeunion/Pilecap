"""Negative: an honest new leaf with its marker updated stays silent.

The parent is DERIVED, not typed. `{{leaf:example}}` resolves to whatever
`apps/example`'s single graph leaf is at plant time, so this fixture is a proper
single successor on any tree — which is the whole of what it claims. It was
typed until P7 Q-32b, and four rungs in a row had to re-chain it by hand; the
fifth (R-e's `0011_widget_search_vector`) landed while nobody did, and the plant
forked the graph into two leaves and fired the rule it exists to keep quiet.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("example", "{{leaf:example}}")]
    operations = []
