/**
 * THE FOUR STORIES. Exactly `REQUIRED_STORY_EXPORTS`, and the test beside them
 * asserts set-equality against that constant rather than against a hand list —
 * a lint, a story and a component cannot then disagree about what the four are.
 *
 * FIXTURES ARE TYPED AGAINST THE GENERATED SHAPE, NEVER AGAINST THE COMPONENT
 * THAT READS THEM (fe-conventions §6.7). A fixture typed from the component is
 * a mirror, and a mirror confirms whatever it is shown: that is exactly how a
 * hand-typed `{ label, href }` shipped, agreed with its own test, and rendered
 * `undefined` on every source link of a live surface.
 */

import type { OrganizationPage } from "@/api/client";
import type { SurfaceState, WireRefusal } from "@pilecap/ui/state";
import { WELCOME_COPY as C } from "@/copy/welcome";
import { WelcomeScreen } from "@/screens/welcome/welcome-screen";

/** The document's own shape, not a retyping of it. */
const PAGE: OrganizationPage = {
    items: [
        {
            id: "0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f21",
            name: "Northern branch",
            slug: "northern-branch",
            parent_id: null,
            path: "0000",
            depth: 0,
            created_at: "2026-08-23T09:30:00.000Z",
            updated_at: "2026-08-23T09:30:00.000Z",
        },
        {
            id: "0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f22",
            name: "Harbour office",
            slug: "harbour-office",
            parent_id: "0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f21",
            path: "0000.0001",
            depth: 1,
            created_at: "2026-08-23T09:30:00.000Z",
            updated_at: "2026-08-23T09:30:00.000Z",
        },
    ],
    has_more: false,
    next_cursor: null,
    count: null,
};

/** A refusal the DOCUMENT can actually answer with, on this operation. */
const REFUSED_HAT: WireRefusal = {
    code: "addressing_header_not_honoured",
    detail: "You are who you say you are, and this request named a place it cannot act in.",
    remedies: [
        { label: "Name an organization you hold a role on, or above", destination: "header:X-Org" },
        { label: "Check which memberships you actually hold", destination: "self:membership" },
    ],
};

export function Loading() {
    const state: SurfaceState<OrganizationPage> = { kind: "loading" };
    return <WelcomeScreen state={state} hat={null} />;
}

export function Empty() {
    const state: SurfaceState<OrganizationPage> = {
        kind: "empty",
        nextAct: { label: C.emptyLabel, detail: C.emptyDetail },
    };
    return <WelcomeScreen state={state} hat={null} />;
}

export function Error() {
    const state: SurfaceState<OrganizationPage> = {
        kind: "error",
        refusal: { kind: "registry", refusal: REFUSED_HAT },
    };
    return <WelcomeScreen state={state} hat="a-hat-you-do-not-hold" />;
}

export function Ready() {
    const state: SurfaceState<OrganizationPage> = { kind: "ready", data: PAGE };
    return <WelcomeScreen state={state} hat="harbour-office" />;
}
