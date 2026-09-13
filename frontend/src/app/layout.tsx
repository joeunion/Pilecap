import type { Metadata } from "next";
import type { ReactNode } from "react";

// THE TOKEN ENTRANCE, and the only stylesheet imported anywhere in this tree.
// A second stylesheet is fe-conventions §2's violation V2; the rule exists so
// that "which file painted this" has one answer.
import "@/tokens/tokens.css";

export const metadata: Metadata = {
    title: "Welcome",
};

/**
 * The root layout — a FROZEN LAYER (fe-conventions §9): a rung that must change
 * it says so up front and takes the layer alone while the rest of a wave runs
 * beside it.
 */
export default function RootLayout({ children }: { readonly children: ReactNode }) {
    return (
        <html lang="en">
            <body>{children}</body>
        </html>
    );
}
