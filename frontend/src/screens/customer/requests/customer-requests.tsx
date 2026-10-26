// golden: portal begin
// patterns: §5, §8, §10, §13, §14, §15
/**
 * EXAMPLE — the customer's requests page: the card that sends one (§10) above
 * the list of the ones they can see (§8). The customer's ONE write lives here.
 *
 * It renders; it never fetches or writes (fe-conventions §4, Law 4). The route
 * hands it the two reads as states and a `send` it calls with the draft; the
 * card keeps only the draft and says whether a send is in flight — the press
 * stays live while it is, and a second press is not a second request (the
 * route's one intent key answers it).
 */

import "@/screens/customer/customer-face.css";

import { useState } from "react";

import type { PortalRequestPage, WidgetPage } from "@/api/client";
import { CUSTOMER_COPY as C } from "@/copy/customer";
import { CUSTOMER_SURFACE } from "@/screens/customer/surface";
import { RefusalPanel } from "@pilecap/ui/refusal-panel";
import { pathFor } from "@pilecap/ui/routes";
import type { Refusal, SurfaceState } from "@pilecap/ui/state";
import { unhandledState } from "@pilecap/ui/state";

/** Where the card stands: drafting, sending, sent, or refused with the server's words. */
export type SendState =
    | { readonly kind: "draft" }
    | { readonly kind: "sending" }
    | { readonly kind: "sent" }
    | { readonly kind: "refused"; readonly refusal: Refusal };

export type CustomerRequestsProps = {
    readonly requests: SurfaceState<PortalRequestPage>;
    readonly widgets: SurfaceState<WidgetPage>;
    /** The widget a door arrived carrying (`?widget=`), chosen at first. */
    readonly chosen: string;
    readonly sending: SendState;
    readonly send: (draft: { readonly widgetId: string; readonly note: string }) => void;
};

export function CustomerRequests({ requests, widgets, chosen, sending, send }: CustomerRequestsProps) {
    return (
        <main className="customer-page">
            <h1 className="customer-title">{C.requestsTitle}</h1>
            <SendCard widgets={widgets} chosen={chosen} sending={sending} send={send} />
            <List state={requests} />
        </main>
    );
}

function SendCard({
    widgets,
    chosen,
    sending,
    send,
}: Pick<CustomerRequestsProps, "widgets" | "chosen" | "sending" | "send">) {
    const [widgetId, setWidgetId] = useState(chosen);
    const [note, setNote] = useState("");
    const [missing, setMissing] = useState<string | null>(null);
    const options = widgets.kind === "ready" ? widgets.data.items : [];

    function onSubmit(event: { preventDefault(): void }) {
        event.preventDefault();
        if (sending.kind === "sending") return;
        const widget = widgetId || chosen;
        if (widget === "") {
            setMissing(C.chooseWidget);
            return;
        }
        if (note.trim() === "") {
            setMissing(C.writeNote);
            return;
        }
        setMissing(null);
        send({ widgetId: widget, note });
    }

    return (
        <section className="customer-card" aria-label={C.sendTitle} data-seat="request-send">
            <h2 className="customer-section">{C.sendTitle}</h2>
            <form method="post" onSubmit={onSubmit}>
                <label className="customer-field">
                    <span>{C.widgetLabel}</span>
                    <select name="widget_id" value={widgetId || chosen} onChange={(event) => setWidgetId(event.target.value)}>
                        <option value="" />
                        {options.map((widget) => (
                            <option key={widget.id} value={widget.id}>
                                {widget.name}
                            </option>
                        ))}
                    </select>
                </label>
                <label className="customer-field">
                    <span>{C.noteLabel}</span>
                    <textarea name="note" rows={4} value={note} onChange={(event) => setNote(event.target.value)} />
                </label>
                {missing === null ? null : <p className="customer-said">{missing}</p>}
                {sending.kind === "refused" ? (
                    <RefusalPanel
                        refusal={sending.refusal}
                        refused={C.sendRefusedLabel}
                        surface={CUSTOMER_SURFACE}
                    />
                ) : null}
                <p className="customer-act-line">
                    <button type="submit" className="customer-act">
                        {sending.kind === "sending" ? C.sendingAct : C.sendAct}
                    </button>
                    {sending.kind === "sent" ? <span className="customer-fact"> {C.sentLabel}</span> : null}
                </p>
            </form>
        </section>
    );
}

function List({ state }: { readonly state: SurfaceState<PortalRequestPage> }) {
    switch (state.kind) {
        case "loading":
            return <p className="customer-quiet">{C.loading}</p>;
        case "empty":
            return (
                <section>
                    <p className="customer-next">{state.nextAct?.label}</p>
                    <p className="customer-next-detail">{state.nextAct?.detail}</p>
                </section>
            );
        case "error":
            return (
                <RefusalPanel
                    refusal={state.refusal}
                    surface={CUSTOMER_SURFACE}
                />
            );
        case "ready":
            return (
                <ul className="customer-rows">
                    {state.data.items.map((request) => (
                        <li key={request.id}>
                            <a
                                className="customer-row"
                                href={pathFor("portal_request-detail", { id: request.id }, undefined, CUSTOMER_SURFACE) ?? undefined}
                            >
                                <span className="customer-name">{request.note}</span>
                                <span className="customer-fact">{request.requester_email}</span>
                            </a>
                        </li>
                    ))}
                </ul>
            );
    }
    return unhandledState(state);
}
// golden: portal end
