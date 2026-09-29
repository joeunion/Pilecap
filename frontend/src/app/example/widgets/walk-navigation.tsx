"use client";

import { useRouter } from "next/navigation";
import type { ReactNode } from "react";

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
