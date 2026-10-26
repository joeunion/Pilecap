"use client";
// golden: portal begin

/** EXAMPLE — one widget, as the customer reads it. The route fetches; the screen renders. */

import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { getWidget, type WidgetDetail } from "@/api/client";
import { CustomerWidgetRecord } from "@/screens/customer/widgets/customer-widget-record";
import type { SurfaceState } from "@pilecap/ui/state";

export default function CustomerWidgetPage() {
    const { id } = useParams<{ id: string }>();
    const [state, setState] = useState<SurfaceState<WidgetDetail>>({ kind: "loading" });

    const read = useRef(false);
    useEffect(() => {
        if (read.current) return;
        read.current = true;
        void getWidget(id, null).then((answer) => {
            setState(answer.kind === "refused" ? { kind: "error", refusal: answer.refusal } : { kind: "ready", data: answer.data });
        });
    }, [id]);

    return <CustomerWidgetRecord state={state} />;
}
// golden: portal end
