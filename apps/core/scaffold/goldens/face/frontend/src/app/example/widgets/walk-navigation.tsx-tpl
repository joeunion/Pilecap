// golden: face begin
"use client";

import { useRouter } from "next/navigation";
import type { ReactNode } from "react";

import { useEvents } from "@/api/use-events";
import { walkNavigation } from "@/screens/widget/widget-list.stories";

/**
 * EXAMPLE — the dev walk's router, handed to the stories: a press that lands on
 * another page (the list bar's *Merge*, to the survivor's record) goes there
 * through the app router, as a product's route would.
 */
export function WalkNavigation({ children }: { readonly children: ReactNode }) {
    const router = useRouter();
    return <walkNavigation.Provider value={(href) => router.push(href)}>{children}</walkNavigation.Provider>;
}

/**
 * EXAMPLE — the worked live board: the walk listens on the tenant's event
 * socket through the kit's one hook (`useEvents`) and says the feed's state as
 * `data-board` — `live` once the socket is open, which takes a session and a
 * running backend. A product's own list page hands the same word to its screen.
 */
export function WalkBoard({ children }: { readonly children: ReactNode }) {
    const feed = useEvents(null, ["widget"]);
    return <div data-board={feed.board}>{children}</div>;
}
// golden: face end
