

def canary_rename_widget(*, widget, name):
    widget.name = name
    widget.save()
