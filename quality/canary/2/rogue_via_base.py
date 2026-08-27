

class RogueBase(models.Model):
    class Meta:
        abstract = True


class RogueSecond(RogueBase):
    label2 = models.CharField(max_length=32)
