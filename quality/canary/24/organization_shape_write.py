

def _canary_move_by_hand(organization, elsewhere):
    organization.parent = Organization.objects.filter(slug="elsewhere").first()
    organization.path = elsewhere.path + ".0000"
    organization.save(update_fields=["parent", "path"])
