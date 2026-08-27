"""The shapes that cross this app's workflow boundary.

Plain dataclasses in a module that imports nothing but the standard library,
because everything here is serialised into Temporal's history and replayed from
it — possibly years later, by a worker running code nobody has looked at since.
A workflow argument that was a `Message` could not be replayed at all: the row
will have moved on.

The ids are strings rather than `UUID`s for the same reason: what comes back
out of history is JSON, and a string parsed once, in the activity, at the edge
of the database, is one conversion in one place.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PolicyStep:
    """One rung of an escalation, as the interpreter sees it.

    A plain dataclass rather than the `DeliveryPolicy` row, because this is what
    crosses into workflow history: the run carries a **snapshot** of the steps
    it was started with and never reads the policy again (rule 9, and ADR
    comms-5's generalisation). Revising a policy while a run is mid-wait
    therefore cannot change what that run does — the new version is for the next
    send, and the run in flight finishes the plan it was given. A run that
    re-read the row would be a run whose history no longer explains its own
    decisions.

    `escalate_when` is a closed set of two: `"delivered"` means *go on to the
    next step unless the transport says this one arrived*, and `"none"` means
    *this is the end of the chain*. `services._policy_steps` is the one place
    the set is enforced; by the time a step is here it is already legal.
    """

    channel: str = ""
    template: str = ""
    #: How long to hold the run open for a delivery status before deciding this
    #: step did not land. Zero means "do not wait at all" — escalate straight
    #: on, which is what a step whose whole job is to fan out wants.
    wait_seconds: int = 0
    escalate_when: str = "none"


@dataclass
class DeliverMessage:
    """What `DeliverMessageWorkflow` is started with.

    The tenant is deliberately not here: it rides on the workflow's headers
    (`apps.workflows.context`) and is restored inside the activity, so no caller
    can reach into somebody else's tenant by putting the wrong id in a payload.

    `steps` **empty is the ordinary send** — one message, delivered, then the
    72-hour wait for a provider status that C2-comms-a landed. A policy fills
    it, and the same interpreter walks it. One code path, two behaviours, which
    is why the no-policy send is unchanged rather than merely similar.

    `first_step_status` is what `send()` already decided about step 1, carried
    rather than looked up: the interpreter may not touch the ORM, and a message
    the consent wall refused must not be handed to a transport. It defaults to
    `queued`, which is every no-policy send.

    **The last two fields are T4's, and both default to what every send before
    this shipped meant** — a payload already in flight when this shipped
    deserialises into exactly the behaviour it had.
    """

    message_id: str
    steps: list[PolicyStep] = field(default_factory=list)
    first_step_status: str = "queued"
    #: How long to sleep before trying at all: `send_at` as a duration, and the
    #: quiet-hours window's remainder when the wall deferred this at queue time
    #: **Seconds and not an instant**, for `DeliveryAttempt.defer_seconds`'
    #: reason — the workflow may import `timedelta` and nothing else from
    #: `datetime`, so a duration is a thing it can act on and an instant is a
    #: thing it would have to parse. Zero is every send that is not scheduled
    #: and not deferred, which is almost all of them.
    delay_seconds: int = 0
    #: The opaque per-message id this delivery hands its transport, so a
    #: provider can tell a retry of one send from a second send (ADR
    #: comms-9's deferred nonce, its trigger fired). Carried on the payload
    #: rather than recomputed in the activity because it is also in the run's
    #: OWN id — one value, minted once in `send()`, and a retry that recomputed
    #: it from a row that had moved on would be a second value pretending to be
    #: the first. Empty on a payload written before T4, which reads as "stamp
    #: nothing", which is what those runs did.
    nonce: str = ""


@dataclass
class SendStep:
    """Ask the world to start one *later* step of a policy.

    `message_id` is step 1's message and it is the **anchor**: the recipient,
    the context, the acting organization and the policy's name and version are
    all read from that row inside the activity. The workflow carries an id and a
    step number, not a copy of somebody's customer data — a payload is history,
    and history is forever.
    """

    message_id: str
    step: int
    channel: str
    template: str


@dataclass
class StepStarted:
    """What came of asking. A new message, and what the consent wall said.

    `status` is `queued` when it may go out and `suppressed` when it may not —
    the interpreter needs the difference, because a suppressed step is not
    delivered to anybody and therefore has nothing to wait for.

    **`deferred_seconds` is the third answer**, and it is a duration
    rather than a fourth status word because the interpreter needs the number
    anyway: a step the quiet-hours wall held is `queued` — which is true, the
    message is still going out — and the seconds say how long the run waits
    before handing it over. Zero is every step that was not deferred, which is
    almost all of them, and a payload written before this field existed deserialises to
    zero and behaves exactly as it did.

    Naming it as a duration also keeps the vocabulary honest one level up:
    `suppressed` and `queued` are `Message.Status` values that really are on the
    row, and a `deferred` status word here would be a fourth thing that is not.
    """

    message_id: str
    status: str
    #: How long the interpreter waits before handing this step to a transport.
    #: See the class docstring; zero is every step that was not deferred.
    deferred_seconds: int = 0
    #: This step's own delivery nonce (T4). Every step of an escalation is its
    #: own `Message` row and therefore its own send, so it gets its own opaque
    #: id — a person who is texted and then emailed received two messages, not
    #: one message twice, and a provider must not be told otherwise. Minted by
    #: `send_step` from the row it just wrote, exactly as `send()` mints step
    #: one's. Empty on a payload written before T4.
    nonce: str = ""


@dataclass
class DeliveryStatus:
    """What a provider's status webhook tells a waiting run.

    `message_id` is here even though today's run carries exactly one message,
    and that is deliberate rather than speculative: C2-comms-b's escalation
    interpreter sends several messages from one run and has to know *which*
    step's status arrived. A signal payload is history — adding a field to one
    already in flight is a replay problem — so the field that will be needed is
    the field that ships.

    `status` is one of `Message.Status`'s reported three, as a plain string:
    what comes back out of history is JSON, and the workflow only ever compares
    it, never resolves it to a row.
    """

    message_id: str
    status: str


@dataclass
class DeliveryAttempt:
    """What the sending activity got back from the transport — **or from the wall.**

    `provider` is which transport carried it (`smtp`, `locmem`, an ESP's name);
    `provider_message_id` is what that transport called the message, which is
    the handle a support conversation with the provider starts from.

    The last three fields are ADR comms-10's, and they exist because the
    interpreter may not read a row (house rule 9) and therefore cannot see what
    the edge wall decided. Before ADR comms-10 it could not tell "handed over" from
    "refused at the edge" at all, so a refused message sat out the seventy-two
    hour status wait before its run closed as a zombie. Now the refusal comes
    back on the result, with the one thing that decides what to do about it:

    * `edge_refused_at` — when the wall refused, ISO-8601, `None` when it did
      not. Its presence *is* the refusal; the timestamp is what a history reader
      needs to line the refusal up against the timer that follows it.
    * `refusal_lever` — `"permanent"` (the message dies and the run closes
      promptly) or `"temporal"` (the message waits). Carried explicitly rather
      than inferred from a duration, because "defer for zero seconds" and "do
      not defer" are different instructions.
    * `defer_seconds` — how long the temporal lever has left to run, measured
      from `edge_refused_at`. **Seconds and not a timestamp**, deliberately: the
      workflow may import `timedelta` and nothing else from `datetime`, so a
      duration is a thing it can act on and an instant is a thing it would have
      to parse. Zero is legal and means "re-judge now".
    """

    provider: str = ""
    provider_message_id: str = ""
    edge_refused_at: str | None = None
    refusal_lever: str = ""
    defer_seconds: int = 0


@dataclass
class MessageOutcome:
    """What the terminal activity records: which message ended, and how.

    One shape for both endings rather than two activities, because the workflow
    has to call exactly one of them on every path and a pair would eventually be
    a path that called neither.
    """

    message_id: str
    status: str
    provider: str = ""
    provider_message_id: str = ""
    error: str = ""


@dataclass
class RunFinished:
    """What `mark_run_finished` is told when this app's workflow ends.

    The activity belongs to `apps.workflows` and is invoked **by name**, which
    is how every activity is invoked (house rule 9) — so the shape crosses the
    boundary and the class does not. It is restated here rather than imported
    because a workflow module may import its own `types.py` and nothing else.
    Keep the three fields matching `apps.workflows.types.MarkRunFinished`; the
    worker deserialises into that.
    """

    workflow_id: str
    status: str
    error: str = ""
