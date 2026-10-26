// golden: portal begin
import { fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { PortalRequest, PortalRequestPage, WidgetDetail, WidgetPage } from "@/api/client";
import { CUSTOMER_COPY as C } from "@/copy/customer";
import { CustomerRequestRecord } from "@/screens/customer/requests/customer-request-record";
import { CustomerRequests, type SendState } from "@/screens/customer/requests/customer-requests";
import { CUSTOMER_SURFACE } from "@/screens/customer/surface";
import { CustomerWidgetList } from "@/screens/customer/widgets/customer-widget-list";
import { CustomerWidgetRecord } from "@/screens/customer/widgets/customer-widget-record";
import { RefusalPanel } from "@pilecap/ui/refusal-panel";
import { ROUTE_TABLE, routesOn } from "@pilecap/ui/routes";
import type { Refusal, SurfaceState } from "@pilecap/ui/state";
import { VERB_TABLE } from "@pilecap/ui/verbs";

/** Fixtures typed against the GENERATED shapes (fe-conventions §6.7), never the screens'. */
const WIDGET: WidgetDetail = {
    id: "0196a000-0000-7000-8000-000000000001",
    name: "Left mount",
    notes: "Needs the heavy-duty bracket.",
    owner_id: "0196a000-0000-7000-8000-000000000002",
    owner_email: "dana@example.com",
    tenant_id: "0196a000-0000-7000-8000-000000000003",
    organization_id: "0196a000-0000-7000-8000-000000000004",
    organization_name: "Acme",
    organization_slug: "acme",
    external_ref: "",
    status: "draft",
    version: 1,
    created_at: "2026-09-30T09:00:00Z",
    updated_at: "2026-09-30T09:00:00Z",
    allowed_acts: [],
    tags: [],
};
const WIDGETS: WidgetPage = { items: [WIDGET], has_more: false, next_cursor: null, count: null };
const REQUEST: PortalRequest = {
    id: "0196a000-0000-7000-8000-000000000009",
    widget_id: WIDGET.id,
    note: "Can you send another?",
    priority: "normal",
    requester_id: "0196a000-0000-7000-8000-000000000005",
    requester_email: "pat@customer.example",
    tenant_id: WIDGET.tenant_id,
    organization_id: WIDGET.organization_id,
    created_at: "2026-09-30T10:00:00Z",
    updated_at: "2026-09-30T10:00:00Z",
};
const REQUESTS: PortalRequestPage = { items: [REQUEST], has_more: false, next_cursor: null, count: null };
const REFUSED: Refusal = {
    kind: "registry",
    refusal: { code: "forbidden", detail: "You may not send requests about widgets here.", remedies: [] },
};

/** Every family verb's pressed word, read off the verb table — never typed here. */
const FAMILY_WORDS: readonly string[] = VERB_TABLE.flatMap((row) => row.pressed);

function states<T>(ready: T): readonly [string, SurfaceState<T>][] {
    return [
        ["loading", { kind: "loading" }],
        ["empty", { kind: "empty", nextAct: { label: C.noWidgets } }],
        ["error", { kind: "error", refusal: REFUSED }],
        ["ready", { kind: "ready", data: ready }],
    ];
}

describe("the customer's pages are its surface's rows", () => {
    it("the table draws four pages on the customer surface, none of them a staff page", () => {
        const drawn = routesOn(CUSTOMER_SURFACE);
        expect(drawn.length).toBeGreaterThan(0);
        for (const row of drawn) {
            expect(row.surfaces).toEqual([CUSTOMER_SURFACE]);
            expect(row.devOnly).toBe(false);
        }
        expect(ROUTE_TABLE.filter((row) => row.surfaces !== "*" && row.surfaces.includes(CUSTOMER_SURFACE))).toEqual(drawn);
    });
});

describe("the widget, read-only", () => {
    it.each(states(WIDGETS))("the list renders its %s state", (_name, state) => {
        const { container } = render(<CustomerWidgetList state={state} />);
        expect(container.textContent).not.toContain("undefined");
    });

    it.each(states(WIDGET))("the record renders its %s state", (_name, state) => {
        const { container } = render(<CustomerWidgetRecord state={state} />);
        expect(container.textContent).not.toContain("undefined");
    });

    it("a row is a door to the customer's own record page", () => {
        const { container } = render(<CustomerWidgetList state={{ kind: "ready", data: WIDGETS }} />);
        expect(container.querySelector(`a[href="/widgets/${WIDGET.id}"]`)?.textContent).toContain(WIDGET.name);
    });

    it("the record offers no family act — no archive, no edit, no move — and one door to ask", () => {
        const { container } = render(<CustomerWidgetRecord state={{ kind: "ready", data: WIDGET }} />);
        expect(container.querySelector("[data-act]")).toBeNull();
        expect(container.querySelector("button")).toBeNull();
        for (const word of FAMILY_WORDS) {
            expect(container.textContent).not.toContain(word);
        }
        expect(container.querySelector(`a[href="/requests?widget=${WIDGET.id}"]`)?.textContent).toBe(C.askAboutAct);
    });
});

describe("the requests page and its one write", () => {
    function page(sending: SendState, send = vi.fn()) {
        const view = render(
            <CustomerRequests
                requests={{ kind: "ready", data: REQUESTS }}
                widgets={{ kind: "ready", data: WIDGETS }}
                chosen={WIDGET.id}
                sending={sending}
                send={send}
            />,
        );
        return { ...view, send };
    }

    afterEach(() => {
        vi.restoreAllMocks();
    });

    it.each(states(REQUESTS))("the list renders its %s state", (_name, state) => {
        const { container } = render(
            <CustomerRequests requests={state} widgets={{ kind: "loading" }} chosen="" sending={{ kind: "draft" }} send={vi.fn()} />,
        );
        expect(container.querySelector("form")).not.toBeNull();
        expect(container.textContent).not.toContain("undefined");
    });

    it.each(states(REQUEST))("the record renders its %s state", (_name, state) => {
        const { container } = render(<CustomerRequestRecord state={state} />);
        expect(container.textContent).not.toContain("undefined");
    });

    it("sends the chosen widget and the words, once", () => {
        const { getByRole, getByLabelText, send } = page({ kind: "draft" });
        fireEvent.change(getByLabelText(C.noteLabel), { target: { value: "Send another?" } });
        fireEvent.click(getByRole("button", { name: C.sendAct }));
        expect(send).toHaveBeenCalledTimes(1);
        expect(send).toHaveBeenCalledWith({ widgetId: WIDGET.id, note: "Send another?" });
    });

    it("says what is missing and sends nothing when the words are empty", () => {
        const { getByRole, send, container } = page({ kind: "draft" });
        fireEvent.click(getByRole("button", { name: C.sendAct }));
        expect(send).not.toHaveBeenCalled();
        expect(container.textContent).toContain(C.writeNote);
    });

    it("while a send is in flight the act says so and a second press is not a second send", () => {
        const { getByRole, getByLabelText, send } = page({ kind: "sending" });
        fireEvent.change(getByLabelText(C.noteLabel), { target: { value: "Again?" } });
        fireEvent.click(getByRole("button", { name: C.sendingAct }));
        expect(send).not.toHaveBeenCalled();
    });

    it("a refused send shows the server's words under the card's own label", () => {
        const { container } = page({ kind: "refused", refusal: REFUSED });
        expect(container.textContent).toContain(C.sendRefusedLabel);
        expect(container.textContent).toContain("You may not send requests about widgets here.");
    });
});

describe("a remedy on the customer surface opens the customer's page", () => {
    afterEach(() => {
        vi.unstubAllEnvs();
    });

    it("in production the widget list remedy is a live door to /widgets, not the staff walk", () => {
        vi.stubEnv("NODE_ENV", "production");
        const { container } = render(
            <RefusalPanel
                refusal={{
                    kind: "registry",
                    refusal: {
                        code: "not_found",
                        detail: "Nothing here.",
                        remedies: [{ label: "See the widgets", destination: "route:widget-list" }],
                    },
                }}
                surface={CUSTOMER_SURFACE}
            />,
        );
        expect(container.querySelector('a[href="/widgets"]')?.textContent).toBe("See the widgets");
    });
});
// golden: portal end
