// golden: portal begin
// patterns: §6, §9, §13, §15
/**
 * EXAMPLE — one widget as a customer reads it: its name, its notes, where it
 * lives and the words on it, and ONE door — to send a request about it. No
 * family act: the customer surface offers none (`allowed_acts` is empty on
 * this host), so no Edit, Archive, Move or Merge is ever drawn here.
 */

import "@/screens/customer/customer-face.css";

import type { WidgetDetail } from "@/api/client";
import { CUSTOMER_COPY as C } from "@/copy/customer";
import { CUSTOMER_SURFACE } from "@/screens/customer/surface";
import { RefusalPanel } from "@pilecap/ui/refusal-panel";
import { pathFor } from "@pilecap/ui/routes";
import type { SurfaceState } from "@pilecap/ui/state";
import { unhandledState } from "@pilecap/ui/state";

export function CustomerWidgetRecord({ state }: { readonly state: SurfaceState<WidgetDetail> }) {
    const list = pathFor("widget-list", {}, undefined, CUSTOMER_SURFACE);
    return (
        <main className="customer-page">
            {list === null ? null : (
                <a className="customer-crumb" href={list}>
                    {C.widgetsTitle}
                </a>
            )}
            <Body state={state} />
        </main>
    );
}

function Body({ state }: { readonly state: SurfaceState<WidgetDetail> }) {
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
            const widget = state.data;
            const ask = pathFor("portal_request-list", {}, undefined, CUSTOMER_SURFACE);
            return (
                <article>
                    <h1 className="customer-record-name">
                        {widget.name}
                    </h1>
                    <p className="customer-fact customer-fact-line">
                        {widget.organization_name}
                    </p>
                    {widget.notes === "" ? null : <p className="customer-notes">{widget.notes}</p>}
                    {(widget.tags ?? []).length === 0 ? null : (
                        <p className="customer-fact customer-fact-line">
                            {(widget.tags ?? []).map((tag) => tag.name).join(" · ")}
                        </p>
                    )}
                    {ask === null ? null : (
                        <a className="customer-door" data-seat="record-acts" href={`${ask}?widget=${encodeURIComponent(widget.id)}`}>
                            {C.askAboutAct}
                        </a>
                    )}
                </article>
            );
        }
    }
    return unhandledState(state);
}
// golden: portal end
