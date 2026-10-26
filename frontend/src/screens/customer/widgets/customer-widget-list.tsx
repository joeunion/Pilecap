// golden: portal begin
// patterns: §5, §8, §13, §14, §15
/**
 * EXAMPLE — the widget list as a customer reads it: the staff noun, drawn
 * read-only from the same generated client. A total function from
 * `SurfaceState` to markup; it fetches nothing (the route does) and offers no
 * act — the customer surface offers none, and the rows' `allowed_acts` say so.
 */

import "@/screens/customer/customer-face.css";

import type { WidgetPage } from "@/api/client";
import { CUSTOMER_COPY as C } from "@/copy/customer";
import { CUSTOMER_SURFACE } from "@/screens/customer/surface";
import { RefusalPanel } from "@pilecap/ui/refusal-panel";
import { pathFor } from "@pilecap/ui/routes";
import type { SurfaceState } from "@pilecap/ui/state";
import { unhandledState } from "@pilecap/ui/state";

export function CustomerWidgetList({ state }: { readonly state: SurfaceState<WidgetPage> }) {
    return (
        <main className="customer-page">
            <h1 className="customer-title">{C.widgetsTitle}</h1>
            <Body state={state} />
        </main>
    );
}

function Body({ state }: { readonly state: SurfaceState<WidgetPage> }) {
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
                    {state.data.items.map((widget) => (
                        <li key={widget.id}>
                            <a
                                className="customer-row"
                                href={pathFor("widget-detail", { id: widget.id }, undefined, CUSTOMER_SURFACE) ?? undefined}
                            >
                                <span className="customer-name">{widget.name}</span>
                                <span className="customer-fact">{widget.organization_name}</span>
                            </a>
                        </li>
                    ))}
                </ul>
            );
    }
    return unhandledState(state);
}
// golden: portal end
