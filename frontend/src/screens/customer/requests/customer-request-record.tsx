// golden: portal begin
// patterns: §6, §9, §13, §15
/**
 * EXAMPLE — one request as its reader sees it: what was asked, about which
 * widget, by whom and when. Read-only — nobody edits a request.
 */

import "@/screens/customer/customer-face.css";

import type { PortalRequest } from "@/api/client";
import { CUSTOMER_COPY as C } from "@/copy/customer";
import { CUSTOMER_SURFACE } from "@/screens/customer/surface";
import { RefusalPanel } from "@pilecap/ui/refusal-panel";
import { pathFor } from "@pilecap/ui/routes";
import type { SurfaceState } from "@pilecap/ui/state";
import { unhandledState } from "@pilecap/ui/state";

export function CustomerRequestRecord({ state }: { readonly state: SurfaceState<PortalRequest> }) {
    const list = pathFor("portal_request-list", {}, undefined, CUSTOMER_SURFACE);
    return (
        <main className="customer-page">
            {list === null ? null : (
                <a className="customer-crumb" href={list}>
                    {C.requestsTitle}
                </a>
            )}
            <Body state={state} />
        </main>
    );
}

function Body({ state }: { readonly state: SurfaceState<PortalRequest> }) {
    switch (state.kind) {
        case "loading":
            return <p className="customer-quiet">{C.loading}</p>;
        case "empty":
            return <p className="customer-quiet">{C.notFoundRecord}</p>;
        case "error":
            return (
                <RefusalPanel
                    refusal={state.refusal}
                    surface={CUSTOMER_SURFACE}
                />
            );
        case "ready": {
            const request = state.data;
            const widget = pathFor("widget-detail", { id: request.widget_id }, undefined, CUSTOMER_SURFACE);
            return (
                <article>
                    <p className="customer-note">{request.note}</p>
                    <dl className="customer-facts">
                        <dt className="customer-fact">{C.widgetLabel}</dt>
                        <dd>
                            {widget === null ? null : (
                                <a className="customer-door" href={widget}>
                                    {C.widgetsTitle}
                                </a>
                            )}
                        </dd>
                        <dt className="customer-fact">{C.askedByLabel}</dt>
                        <dd>{request.requester_email}</dd>
                        <dt className="customer-fact">{C.addedLabel}</dt>
                        <dd>{request.created_at}</dd>
                    </dl>
                </article>
            );
        }
    }
    return unhandledState(state);
}
// golden: portal end
