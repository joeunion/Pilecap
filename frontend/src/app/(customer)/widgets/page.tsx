"use client";
// golden: portal begin

/**
 * EXAMPLE — the customer's widget list. The route fetches; the screen renders
 * (fe-conventions §4, Law 4). The hat is the membership's own (the customer
 * surface chooses the workspace by membership), so none is sent.
 */

import { useEffect, useRef, useState } from "react";

import { listWidgets, type WidgetPage } from "@/api/client";
import { CUSTOMER_COPY as C } from "@/copy/customer";
import { CustomerWidgetList } from "@/screens/customer/widgets/customer-widget-list";
import type { SurfaceState } from "@pilecap/ui/state";

export default function CustomerWidgetsPage() {
    const [state, setState] = useState<SurfaceState<WidgetPage>>({ kind: "loading" });

    // THE ONE-SHOT, AND IT HAS NO LIVE FLAG (fe-conventions §6.3 + §6.4).
    const read = useRef(false);
    useEffect(() => {
        if (read.current) return;
        read.current = true;
        void listWidgets(null).then((answer) => {
            if (answer.kind === "refused") {
                setState({ kind: "error", refusal: answer.refusal });
            } else if (answer.data.items.length === 0) {
                setState({ kind: "empty", nextAct: { label: C.noWidgets, detail: C.noWidgetsDetail } });
            } else {
                setState({ kind: "ready", data: answer.data });
            }
        });
    }, []);

    return <CustomerWidgetList state={state} />;
}
// golden: portal end
