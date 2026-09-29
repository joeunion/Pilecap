import { render } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RefusalPanel } from "@/screens/refusal-panel";
import { remedyDoor } from "@/screens/remedy-door";
import { ROUTE_TABLE } from "@/screens/routes";
import type { Refusal, WireRemedy } from "@/screens/state";

const LIST: WireRemedy = { label: "See the widgets this one depends on", destination: "route:widget-list" };
const UNMAPPED: WireRemedy = { label: "Ask for a wider token", destination: "route:token-mint" };

function refused(remedies: WireRemedy[]): Refusal {
    return { kind: "registry", refusal: { detail: "This widget is still in use.", code: "conflict", remedies } };
}

function panel(remedies: WireRemedy[]) {
    return render(
        createElement(RefusalPanel, {
            refusal: refused(remedies),
            words: { label: "The server refused", remedies: "What you can do" },
        }),
    );
}

describe("the refusal panel draws a route remedy as a live door", () => {
    it("a mapped route: remedy is a real link to the page that draws the operation", () => {
        const { container } = panel([LIST]);
        const link = container.querySelector('a[href="/example/widgets"]');
        expect(link).not.toBeNull();
        expect(link?.textContent).toBe(LIST.label);
        expect(link?.getAttribute("data-destination")).toBe("route:widget-list");
    });

    it("the destination token is never printed to the reader", () => {
        const { container } = panel([LIST, UNMAPPED]);
        expect(container.textContent).not.toContain("route:");
    });

    it("an unmapped url name renders the label unlinked, the token kept in data-destination", () => {
        const { container } = panel([UNMAPPED]);
        const kept = container.querySelector('[data-destination="route:token-mint"]');
        expect(kept).not.toBeNull();
        expect(kept?.tagName).not.toBe("A");
        expect(kept?.textContent).toBe(UNMAPPED.label);
        expect(container.querySelector("a")).toBeNull();
    });

    it("a non-route remedy is the label only", () => {
        const { container } = panel([{ label: "Name the organization to act as", destination: "header:X-Org" }]);
        expect(container.querySelector("a")).toBeNull();
        expect(container.querySelector('[data-destination="header:X-Org"]')?.textContent).toBe(
            "Name the organization to act as",
        );
    });

    it("the seat prop only sets data-seat", () => {
        const { container } = render(
            createElement(RefusalPanel, {
                refusal: refused([]),
                words: { label: "The server refused", remedies: "What you can do" },
                seat: "record-acts",
            }),
        );
        expect(container.querySelector('[role="alert"]')?.getAttribute("data-seat")).toBe("record-acts");
    });
});

describe("remedyDoor", () => {
    it("reads the real route table: the worked list page draws widget-list", () => {
        expect(ROUTE_TABLE.find((row) => row.operation === "widget-list")?.path).toBe("/example/widgets");
    });

    it("every route-table operation on a static path maps to its row", () => {
        const rows = ROUTE_TABLE.filter((row) => row.operation !== null && !row.path.includes("["));
        expect(rows.length).toBeGreaterThan(1);
        for (const row of rows) {
            expect(remedyDoor({ label: "Go there", destination: `route:${row.operation}` })).toEqual({
                kind: "link",
                label: "Go there",
                href: row.path,
                destination: `route:${row.operation}`,
            });
        }
    });

    it("an unknown url name is the label only", () => {
        expect(remedyDoor(UNMAPPED).kind).toBe("label");
    });

    it("a route whose path has a segment the token cannot fill is the label only", () => {
        expect(remedyDoor({ label: "Open the widget", destination: "route:widget-detail" }).kind).toBe("label");
    });

    it("the query is carried as the list's narrowing", () => {
        const door = remedyDoor({ label: "See the archived widgets", destination: "route:widget-list?show=archived" });
        expect(door).toMatchObject({ kind: "link", href: "/example/widgets?show=archived" });
    });

    it.each(["Open widget-list", "Fix invoice_id", "Open 0123456789abcdef0123456789abcdef"])(
        "a label carrying a machine token is not linked: %s",
        (label) => {
            expect(remedyDoor({ label, destination: "route:widget-list" }).kind).toBe("label");
        },
    );

    it("an empty operation is the label only", () => {
        expect(remedyDoor({ label: "Go", destination: "route:" }).kind).toBe("label");
    });
});

describe("a remedy never links to a page that is a 404 in production", () => {
    afterEach(() => {
        vi.unstubAllEnvs();
    });

    it("the route table marks the walks devOnly and the landing not", () => {
        const devOnly = Object.fromEntries(ROUTE_TABLE.map((row) => [row.path, row.devOnly]));
        expect(devOnly).toEqual({
            "/welcome": false,
            "/states": true,
            "/example/widgets": true,
            "/example/widgets/import": true,
            "/example/widgets/[id]": true,
        });
    });

    it("in production, a devOnly operation is the label unlinked, the token kept", () => {
        vi.stubEnv("NODE_ENV", "production");
        expect(remedyDoor(LIST)).toEqual({ kind: "label", label: LIST.label, destination: "route:widget-list" });
        const { container } = panel([LIST]);
        expect(container.querySelector("a")).toBeNull();
        expect(container.querySelector('[data-destination="route:widget-list"]')?.textContent).toBe(LIST.label);
    });

    it("in production, an operation on a page that ships is still a live link", () => {
        vi.stubEnv("NODE_ENV", "production");
        expect(remedyDoor({ label: "See where you are acting", destination: "route:organization-list" })).toMatchObject({
            kind: "link",
            href: "/welcome",
        });
    });

    it("in development, the devOnly page is a live link", () => {
        vi.stubEnv("NODE_ENV", "development");
        expect(remedyDoor(LIST)).toMatchObject({ kind: "link", href: "/example/widgets" });
    });
});
