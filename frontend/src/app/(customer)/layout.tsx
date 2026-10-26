// golden: portal begin
import { headers } from "next/headers";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { readSurfaceOnServer } from "@/api/surface-server";
import { CUSTOMER_SURFACE } from "@/screens/customer/surface";

/**
 * THE CUSTOMER SURFACE'S OWN PAGES, GUARDED ON THE SERVER — a real 404 off it.
 *
 * A server layout for this route group (a group does not change the URL): per
 * request it asks the SAME boot question the client gate asks — the server's
 * one resolver, `GET /api/v1/surface/`, with this request's Host — and a page
 * of this group on a host that is not the customer surface is `notFound()`: a
 * real 404, `noindex`, before any byte of the page. Legal here because this is
 * a NESTED layout (Next refuses `notFound()` only in the root one). The price —
 * these pages render per request — falls on this group alone; the staff pages
 * keep their static prerender and their client-drawn seat
 * (`@/app/surface-gate`).
 *
 * A server that did not answer is not a surface that said no: that is thrown,
 * a 500 a reader can retry, never a 404 that says the page does not exist.
 */
export default async function CustomerLayout({ children }: { readonly children: ReactNode }) {
    const host = (await headers()).get("host") ?? "";
    const answer = await readSurfaceOnServer(host);
    if (answer.kind === "refused" && answer.refusal.kind === "transport") {
        throw new Error(`the surface could not be asked: ${answer.refusal.code}`);
    }
    if (answer.kind !== "ok" || answer.data.surface !== CUSTOMER_SURFACE) {
        notFound();
    }
    return children;
}
// golden: portal end
