"use client";
// golden: portal begin

/**
 * EXAMPLE — the customer's requests page, and the ONE write on this surface.
 *
 * The route fetches and writes; the screen renders (fe-conventions §4). The
 * write goes through the client's one mutation wrapper with the page's token
 * and ONE intent key: minted on the first press of a draft, reused by every
 * retry of it (a double press, a retry after a refusal), and let go only when
 * the server has said the request exists — so a retried send is never a
 * second request. The busy flag is cleared on every path (§6.9).
 */

import { useEffect, useRef, useState } from "react";

import {
    type IntentKey,
    listPortalRequests,
    listWidgets,
    mintIntent,
    type PortalRequestPage,
    readPageToken,
    submitPortalRequest,
    type WidgetPage,
} from "@/api/client";
import { transportFailure } from "@/api/refusals";
import { CUSTOMER_COPY as C } from "@/copy/customer";
import { CustomerRequests, type SendState } from "@/screens/customer/requests/customer-requests";
import type { SurfaceState } from "@pilecap/ui/state";

export default function CustomerRequestsPage() {
    const [requests, setRequests] = useState<SurfaceState<PortalRequestPage>>({ kind: "loading" });
    const [widgets, setWidgets] = useState<SurfaceState<WidgetPage>>({ kind: "loading" });
    const [chosen, setChosen] = useState("");
    const [sending, setSending] = useState<SendState>({ kind: "draft" });
    const intent = useRef<IntentKey | null>(null);

    const read = useRef(false);
    useEffect(() => {
        if (read.current) return;
        read.current = true;
        // The door a widget's record drew carries the widget (`?widget=`); read
        // here, not during render, because there is no `window` on the server.
        setChosen(new URLSearchParams(window.location.search).get("widget") ?? "");
        void listWidgets(null).then((answer) => {
            setWidgets(answer.kind === "refused" ? { kind: "error", refusal: answer.refusal } : { kind: "ready", data: answer.data });
        });
        void listPortalRequests(null).then((answer) => {
            setRequests(listed(answer.kind === "refused" ? answer : { kind: "ok", data: answer.data }));
        });
    }, []);

    async function send(draft: { readonly widgetId: string; readonly note: string }) {
        intent.current ??= mintIntent();
        setSending({ kind: "sending" });
        try {
            const answer = await submitPortalRequest(
                { widget_id: draft.widgetId, note: draft.note },
                null,
                readPageToken(),
                intent.current,
            );
            if (answer.kind === "refused") {
                setSending({ kind: "refused", refusal: answer.refusal });
                return;
            }
            intent.current = null;
            setSending({ kind: "sent" });
            const again = await listPortalRequests(null);
            setRequests(listed(again.kind === "refused" ? again : { kind: "ok", data: again.data }));
        } catch (cause) {
            setSending({ kind: "refused", refusal: transportFailure(cause) });
        }
    }

    return <CustomerRequests requests={requests} widgets={widgets} chosen={chosen} sending={sending} send={(draft) => void send(draft)} />;
}

/** A list answer as the list's state: refused, empty with its next act, or ready. */
function listed(
    answer: { readonly kind: "refused"; readonly refusal: SendRefusal } | { readonly kind: "ok"; readonly data: PortalRequestPage },
): SurfaceState<PortalRequestPage> {
    if (answer.kind === "refused") return { kind: "error", refusal: answer.refusal };
    if (answer.data.items.length === 0) return { kind: "empty", nextAct: { label: C.noRequests, detail: C.noRequestsDetail } };
    return { kind: "ready", data: answer.data };
}

type SendRefusal = Extract<SendState, { kind: "refused" }>["refusal"];
// golden: portal end
