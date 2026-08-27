

def _canary_direct_write(request, widget):
    widget.name = "edited in a door"
    widget.save()
