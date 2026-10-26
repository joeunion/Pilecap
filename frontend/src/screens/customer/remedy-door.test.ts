// golden: portal begin
import { afterEach, describe, expect, it, vi } from "vitest";

import { remedyDoor } from "@pilecap/ui/remedy-door";
import type { RouteRow } from "@pilecap/ui/routes";
import type { WireRemedy } from "@pilecap/ui/state";

/**
 * A REMEDY'S DOOR IS THE ROW OF THE SURFACE IT IS DRAWN ON.
 *
 * Two faces can draw one operation: the staff face's widget walk is a 404 in
 * a production build, the customer face's widget list ships. Which row a remedy
 * reads is the surface's (`routesOn`), for the path AND for whether the page
 * ships — never the first row that happens to draw the operation, which is the
 * other surface's row half the time.
 */
const LIST: WireRemedy = { label: "See the widgets", destination: "route:widget-list" };

function row(path: string, devOnly: boolean, surfaces: readonly string[]): RouteRow {
    return { path, job: "A page.", primarySeat: null, operation: "widget-list", devOnly, surfaces };
}

const STAFF_WALK = row("/example/widgets", true, ["staff"]);
const CUSTOMER_LIST = row("/widgets", false, ["customer"]);

describe("the remedy door reads the row of the surface it is drawn on", () => {
    afterEach(() => {
        vi.unstubAllEnvs();
    });

    it("on the customer surface a live page is a live door, whatever row comes first", () => {
        vi.stubEnv("NODE_ENV", "production");
        const door = remedyDoor(LIST, [STAFF_WALK, CUSTOMER_LIST], "customer");
        expect(door).toEqual({ kind: "link", label: LIST.label, href: "/widgets", destination: LIST.destination });
    });

    it("on the staff surface the customer's page is never the door, and a production 404 is no door", () => {
        vi.stubEnv("NODE_ENV", "production");
        const door = remedyDoor(LIST, [CUSTOMER_LIST, STAFF_WALK], "staff");
        expect(door).toEqual({ kind: "label", label: LIST.label, destination: LIST.destination });
    });

    it("on the staff surface in development the walk is the door", () => {
        vi.stubEnv("NODE_ENV", "development");
        const door = remedyDoor(LIST, [CUSTOMER_LIST, STAFF_WALK], "staff");
        expect(door).toEqual({ kind: "link", label: LIST.label, href: "/example/widgets", destination: LIST.destination });
    });
});
// golden: portal end
