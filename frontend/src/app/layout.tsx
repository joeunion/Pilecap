import type { Metadata } from "next";
import type { ReactNode } from "react";

// THE TOKEN ENTRANCE, and the only stylesheet a route imports. Every other
// sheet is a face's own, beside its screens and imported by them alone (the
// book's §26); a route importing any other is fe-conventions §2's violation
// V2, so "which file painted this" has one answer per face.
import "@/tokens/tokens.css";

import { SurfaceGate } from "@/app/surface-gate";

export const metadata: Metadata = {
    title: "Welcome",
};

/**
 * The root layout — a FROZEN LAYER (fe-conventions §9): a rung that must change
 * it says so up front and takes the layer alone while the rest of a wave runs
 * beside it.
 *
 * EVERY PAGE KNOWS ITS SURFACE, AND NONE WAITS FOR IT. The gate renders the
 * page at once, asks the server which surface this address is, and after the
 * answer replaces a page that surface does not draw with the off-surface seat
 * (`@/app/surface-gate`, which also says why that seat is not a 404 and why no
 * `notFound()` belongs in this layer).
 */
export default function RootLayout({ children }: { readonly children: ReactNode }) {
    return (
        <html lang="en">
            <body>
                <SurfaceGate>{children}</SurfaceGate>
            </body>
        </html>
    );
}
