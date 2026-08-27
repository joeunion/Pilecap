# A breaking change ships a v2 router beside v1, and it SAYS SO. The marker is
# the whole declaration: a version, on a line somebody wrote on purpose, in a
# door module. It replaced a token scan (`_v2\b`, `/v2/`, `V2Router`, …) that an
# ordinary local named `offered_v2` tripped, disarming rules 3/5/13/16/17 for a
# whole commit with nothing anywhere saying so — .
# api-version: 2
