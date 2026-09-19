/**
 * J4 — THE CLIENT'S CLOSE-CODE COMPONENT (design P-14).
 *
 * Not a screen and not a page: a frame a socket-fed surface renders when its
 * socket ends. The surface goes to `error(E)` and hands the refusal here.
 *
 * WHAT IT KNOWS AND WHAT IT DOES NOT. It knows two state NAMES and their
 * words; it does not know that a socket close code is a number, and it must
 * not — `@/api/socket-close` is the one module that does, and this file may
 * not import it (house rule 51: `api` is off the layer chain and reachable
 * only from `app` and `journeys`). The ROUTE that owns the socket calls the
 * seam and hands down the result, which is fe-conventions Law 4 exactly.
 *
 * IT IS A SCREENS-LAYER MODULE for the reason `@/screens/refusal-panel` states
 * at length: the refusal vocabulary reaches a surface through the
 * surface-state seam, and `components/` is below that seam.
 *
 * A10.2 — NO AUTOMATIC RECONNECT. There is no timer in this file and there is
 * not meant to be one: a retry loop in a tab is a workflow wearing a hook
 * (fe-conventions §7), a tab is not durable, and anything that waits or
 * retries is the server's job. The person's click on the one act IS the retry,
 * which is why the act is a plain link and not a handler. Two teeth hold it:
 * a fake-timer assertion that rendering schedules nothing, and a source census
 * over this file and the seam.
 */

import type { Refusal } from "@/screens/state";
import { SOCKET_CLOSE_COPY } from "@/copy/refusals";
import { RefusalPanel, type RefusalAct } from "@/screens/refusal-panel";

/** The designed states, named by the copy that exists for them. */
export type SocketCloseStateName = keyof typeof SOCKET_CLOSE_COPY;

export type SocketClosePanelProps = {
    /** Which designed state this close frame resolved to. */
    readonly state: SocketCloseStateName;
    /** The transport-class refusal the seam minted for it. */
    readonly refusal: Refusal;
    /** The ONE act. Required, and singular. */
    readonly act: RefusalAct;
};

export function SocketClosePanel({ state, refusal, act }: SocketClosePanelProps) {
    return (
        <RefusalPanel
            refusal={refusal}
            words={{
                label: SOCKET_CLOSE_COPY[state].label,
                // A close frame carries no envelope, so there are no remedies
                // to head. The heading is never rendered; it is required by the
                // shape and an empty string is the honest value.
                remedies: "",
            }}
            act={act}
        />
    );
}
