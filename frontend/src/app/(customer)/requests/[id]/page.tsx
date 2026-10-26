"use client";
// golden: portal begin

/** EXAMPLE — one request, read-only. The route fetches; the screen renders. */

import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { getPortalRequest, type PortalRequest } from "@/api/client";
import { CustomerRequestRecord } from "@/screens/customer/requests/customer-request-record";
import type { SurfaceState } from "@pilecap/ui/state";

export default function CustomerRequestPage() {
    const { id } = useParams<{ id: string }>();
    const [state, setState] = useState<SurfaceState<PortalRequest>>({ kind: "loading" });

    const read = useRef(false);
    useEffect(() => {
        if (read.current) return;
        read.current = true;
        void getPortalRequest(id, null).then((answer) => {
            setState(answer.kind === "refused" ? { kind: "error", refusal: answer.refusal } : { kind: "ready", data: answer.data });
        });
    }, [id]);

    return <CustomerRequestRecord state={state} />;
}
// golden: portal end
