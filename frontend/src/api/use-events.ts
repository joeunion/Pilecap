/**
 * THE SOCKET HOOK — the one primitive that opens the tenant's event socket
 * (`ws/events/`, `apps/realtime/consumers.py`). A live page calls
 * `useEvents(tenant, kinds)` and reads what it answers; it never dials, backs
 * off, reconnects or reads a close frame itself.
 *
 * The close is read through `socketCloseState` (`@/api/socket-close`), the
 * one module that knows a close code is a number, so nothing here spells one
 * (fe-conventions §4 Law 1). A withdrawn credential is final — the hook stops
 * and answers the transport refusal; every other close is a drop it dials
 * back from, with a doubling wait capped at `BACKOFF.capMs`.
 *
 * Pushes only: a frame sent while the socket was down is not replayed, so a
 * re-open counts as a change, and a page re-reads its list over REST whenever
 * `changes` moves.
 */

import { useEffect, useState } from "react";

import type { Refusal } from "@/api/refusals";
import { socketCloseRefusal, socketCloseState } from "@/api/socket-close";

/** One frame the socket delivers — `apps/realtime/schemas.py::EventMessage`, mirrored and censused by its test. */
export type EventFrame = {
    readonly name: string;
    readonly v: number;
    readonly payload: Readonly<Record<string, unknown>>;
    readonly correlation_id?: string | null;
    readonly organization_id?: string | null;
    readonly occurred_at?: string;
};

/** Where the board stands: dialling, hearing, waiting to dial back, or stopped for good. */
export type BoardState = "connecting" | "live" | "reconnecting" | "revoked";

/** What the hook answers a page. */
export type LiveEvents = {
    readonly board: BoardState;
    /** The last frame about one of the asked kinds, or `null` before one arrives. */
    readonly last: EventFrame | null;
    /** Moves on every asked-for frame and every re-open: the page re-reads when it does. */
    readonly changes: number;
    /** The transport refusal behind `revoked`; `null` otherwise. */
    readonly refusal: Refusal | null;
};

/** The socket as the hook drives it — the browser's `WebSocket`, or a test's stand-in. */
export type EventSocket = {
    onopen: (() => void) | null;
    onmessage: ((message: { readonly data: unknown }) => void) | null;
    onclose: ((frame: { readonly code: number; readonly reason: string }) => void) | null;
    close(): void;
};

/** How the hook opens a socket at `url`. */
export type Dial = (url: string) => EventSocket;

/** The wait before the next dial: doubling from `firstMs`, never past `capMs`. */
export const BACKOFF = { firstMs: 1_000, capMs: 30_000 } as const;

/** The wait before dial number `attempt + 1` after a drop. */
export function backoffMs(attempt: number): number {
    return Math.min(BACKOFF.capMs, BACKOFF.firstMs * 2 ** Math.min(attempt, 16));
}

/** The socket's same-origin URL for the page at `where`; `tenant` stands in for `X-Tenant`, omitted on `null`. */
export function eventsUrl(where: { readonly protocol: string; readonly host: string }, tenant: string | null): string {
    const scheme = where.protocol === "https:" ? "wss:" : "ws:";
    const query = tenant === null || tenant === "" ? "" : `?tenant=${encodeURIComponent(tenant)}`;
    return `${scheme}//${where.host}/ws/events/${query}`;
}

/** The browser's socket, its three events handed on in the hook's own shape. */
const browserDial: Dial = (url) => {
    const socket = new WebSocket(url);
    const driven: EventSocket = {
        onopen: null,
        onmessage: null,
        onclose: null,
        close: () => socket.close(),
    };
    socket.onopen = () => driven.onopen?.();
    socket.onmessage = (message) => driven.onmessage?.({ data: message.data });
    socket.onclose = (frame) => driven.onclose?.({ code: frame.code, reason: frame.reason });
    return driven;
};

/** A frame's kind: the noun of its `<app>.<noun>.<verb>` name. */
function kindOf(name: string): string {
    return name.split(".")[1] ?? "";
}

/** The data as a frame, or `null` — a pong, or anything that is not one. */
function frameOf(data: unknown): EventFrame | null {
    if (typeof data !== "string") return null;
    try {
        const parsed: unknown = JSON.parse(data);
        if (typeof parsed !== "object" || parsed === null || typeof (parsed as { name?: unknown }).name !== "string") return null;
        return parsed as EventFrame;
    } catch {
        return null;
    }
}

const OPENING: LiveEvents = { board: "connecting", last: null, changes: 0, refusal: null };

/**
 * The tenant's events about `kinds` (each a noun, as `widget` in `example.widget.created`), live.
 *
 * `tenant` is the slug a page acts in, or `null` for the membership's own.
 * The hook owns the dial, the backoff, the reconnect and the withdrawn
 * credential's close; unmounting closes the socket.
 */
export function useEvents(tenant: string | null, kinds: readonly string[], dial: Dial = browserDial): LiveEvents {
    const [feed, setFeed] = useState<LiveEvents>(OPENING);
    const asked = kinds.join(" ");

    useEffect(() => {
        const wanted = new Set(asked.split(" "));
        let stopped = false;
        let opened = false;
        let attempt = 0;
        let socket: EventSocket | null = null;
        let timer: ReturnType<typeof setTimeout> | undefined;

        const connect = () => {
            const next = dial(eventsUrl(window.location, tenant));
            socket = next;
            next.onopen = () => {
                if (stopped) return;
                const again = opened;
                opened = true;
                attempt = 0;
                setFeed((was) => ({ ...was, board: "live", changes: again ? was.changes + 1 : was.changes }));
            };
            next.onmessage = (message) => {
                if (stopped) return;
                const frame = frameOf(message.data);
                if (frame === null || !wanted.has(kindOf(frame.name))) return;
                setFeed((was) => ({ ...was, last: frame, changes: was.changes + 1 }));
            };
            next.onclose = (frame) => {
                if (stopped) return;
                if (socketCloseState(frame) === "socket_credential_withdrawn") {
                    stopped = true;
                    setFeed((was) => ({ ...was, board: "revoked", refusal: socketCloseRefusal(frame) }));
                    return;
                }
                setFeed((was) => ({ ...was, board: "reconnecting" }));
                timer = setTimeout(connect, backoffMs(attempt));
                attempt += 1;
            };
        };

        connect();
        return () => {
            stopped = true;
            clearTimeout(timer);
            socket?.close();
        };
    }, [tenant, asked, dial]);

    return feed;
}
