import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ABNORMAL_CLOSURE, SERVER_CLOSE_CODES } from "@/api/socket-close";
import { backoffMs, type EventSocket, eventsUrl, useEvents } from "@/api/use-events";

/** A socket the test drives: what the hook dialled, and the frames the server would send. */
class FakeSocket implements EventSocket {
    onopen: (() => void) | null = null;
    onmessage: ((message: { readonly data: unknown }) => void) | null = null;
    onclose: ((frame: { readonly code: number; readonly reason: string }) => void) | null = null;
    closed = false;

    constructor(readonly url: string) {}

    close(): void {
        this.closed = true;
    }

    open(): void {
        this.onopen?.();
    }

    push(frame: unknown): void {
        this.onmessage?.({ data: JSON.stringify(frame) });
    }

    drop(code: number): void {
        this.onclose?.({ code, reason: "" });
    }
}

let dialled: FakeSocket[] = [];
const dial = (url: string): FakeSocket => {
    const socket = new FakeSocket(url);
    dialled.push(socket);
    return socket;
};

/** The last socket the hook dialled. */
function current(): FakeSocket {
    const socket = dialled.at(-1);
    if (socket === undefined) throw new Error("the hook dialled nothing");
    return socket;
}

const CREATED = { name: "example.widget.created", v: 1, payload: { id: "w-1" }, correlation_id: null, organization_id: null };

beforeEach(() => {
    dialled = [];
    vi.useFakeTimers();
});

afterEach(() => {
    vi.useRealTimers();
});

describe("useEvents", () => {
    it("connect: dials the tenant's socket and is live on open, counting the kinds it was asked for", () => {
        const { result } = renderHook(() => useEvents("acme", ["widget"], dial));
        expect(dialled).toHaveLength(1);
        expect(current().url).toBe(eventsUrl(window.location, "acme"));
        expect(result.current.board).toBe("connecting");
        act(() => current().open());
        expect(result.current.board).toBe("live");
        act(() => current().push(CREATED));
        expect(result.current.last?.name).toBe("example.widget.created");
        expect(result.current.changes).toBe(1);
        act(() => current().push({ ...CREATED, name: "example.gadget.created" }));
        act(() => current().push({ type: "pong" }));
        expect(result.current.changes).toBe(1);
    });

    it("reconnect after drop: backs off, dials again, and counts the re-open as a change to re-read", () => {
        const { result } = renderHook(() => useEvents(null, ["widget"], dial));
        act(() => current().open());
        act(() => current().drop(ABNORMAL_CLOSURE));
        expect(result.current.board).toBe("reconnecting");
        expect(dialled).toHaveLength(1);
        act(() => vi.advanceTimersByTime(backoffMs(0) - 1));
        expect(dialled).toHaveLength(1);
        act(() => vi.advanceTimersByTime(1));
        expect(dialled).toHaveLength(2);
        act(() => current().drop(ABNORMAL_CLOSURE));
        act(() => vi.advanceTimersByTime(backoffMs(1)));
        expect(dialled).toHaveLength(3);
        act(() => current().open());
        expect(result.current.board).toBe("live");
        expect(result.current.changes).toBe(1);
        expect(backoffMs(1)).toBeGreaterThan(backoffMs(0));
        expect(backoffMs(50)).toBe(backoffMs(51));
    });

    it("4410 → the revoked state: the credential's refusal, and never a redial", () => {
        const { result } = renderHook(() => useEvents(null, ["widget"], dial));
        act(() => current().open());
        act(() => current().drop(SERVER_CLOSE_CODES.CLOSE_KICKED.code));
        expect(result.current.board).toBe("revoked");
        expect(result.current.refusal).toMatchObject({ kind: "transport", code: "socket_credential_withdrawn" });
        act(() => vi.advanceTimersByTime(backoffMs(50) * 2));
        expect(dialled).toHaveLength(1);
    });

    it("unmount closes the socket and dials nothing after", () => {
        const { unmount } = renderHook(() => useEvents(null, ["widget"], dial));
        act(() => current().open());
        unmount();
        expect(current().closed).toBe(true);
        act(() => current().drop(ABNORMAL_CLOSURE));
        act(() => vi.advanceTimersByTime(backoffMs(50) * 2));
        expect(dialled).toHaveLength(1);
    });

    it("the URL is same-origin, the scheme follows the page, and the tenant rides the query", () => {
        expect(eventsUrl({ protocol: "https:", host: "app.example.com" }, null)).toBe("wss://app.example.com/ws/events/");
        expect(eventsUrl({ protocol: "http:", host: "localhost:3000" }, "a b")).toBe("ws://localhost:3000/ws/events/?tenant=a%20b");
    });
});

describe("the hook spells no close code", () => {
    it("reads every close through the seam, never a number of its own", () => {
        const source = readFileSync(resolve(process.cwd(), "src", "api", "use-events.ts"), "utf8");
        const codes = [ABNORMAL_CLOSURE, ...Object.values(SERVER_CLOSE_CODES).map((fact) => fact.code)];
        for (const code of codes) expect(source).not.toContain(String(code));
    });

    it("mirrors the socket frame's fields from apps/realtime/schemas.py", () => {
        const python = readFileSync(resolve(process.cwd(), "..", "apps", "realtime", "schemas.py"), "utf8");
        const body = python.split("class EventMessage(Schema):")[1]?.split("\nclass ")[0] ?? "";
        const fields = [...body.matchAll(/^ {4}([a-z_]+): /gm)].map((found) => found[1]);
        const source = readFileSync(resolve(process.cwd(), "src", "api", "use-events.ts"), "utf8");
        const frame = source.split("export type EventFrame = {")[1]?.split("};")[0] ?? "";
        const mirrored = [...frame.matchAll(/readonly ([a-z_]+)\??: /g)].map((found) => found[1]);
        expect(fields.length).toBeGreaterThan(2);
        expect(new Set(mirrored)).toEqual(new Set(fields));
    });
});
