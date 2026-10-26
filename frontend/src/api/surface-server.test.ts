// @vitest-environment node
import { createServer, type IncomingHttpHeaders, type Server } from "node:http";
import type { AddressInfo } from "node:net";

import { afterEach, describe, expect, it, vi } from "vitest";

/** A stand-in backend that answers `body` with `status` and remembers the headers it was sent. */
function backend(status: number, body: unknown): Promise<{ server: Server; seen: IncomingHttpHeaders[]; origin: string }> {
    const seen: IncomingHttpHeaders[] = [];
    const server = createServer((incoming, outgoing) => {
        seen.push(incoming.headers);
        outgoing.writeHead(status, { "Content-Type": "application/json" });
        outgoing.end(JSON.stringify(body));
    });
    return new Promise((resolve) => {
        server.listen(0, "127.0.0.1", () => {
            const { port } = server.address() as AddressInfo;
            resolve({ server, seen, origin: `http://127.0.0.1:${port}` });
        });
    });
}

/** The stand-in backend a case started, closed after it. */
const started: { server: Server | undefined } = { server: undefined };

afterEach(() => {
    started.server?.close();
    started.server = undefined;
    vi.unstubAllEnvs();
    vi.resetModules();
});

async function asker(origin: string) {
    vi.stubEnv("DJANGO_ORIGIN", origin);
    vi.resetModules();
    return (await import("@/api/surface-server")).readSurfaceOnServer;
}

const CUSTOMER = { surface: "customer", screens: ["/requests"], tenant_rule: "membership" };

describe("the server layout asks the boot question with the request's Host", () => {
    it("sends the Host it was handed — which fetch would not — and answers the surface", async () => {
        const world = await backend(200, CUSTOMER);
        started.server = world.server;
        const read = await asker(world.origin);
        const answer = await read("customer.localhost:3500");
        expect(world.seen[0]?.host).toBe("customer.localhost:3500");
        expect(answer).toEqual({ kind: "ok", data: CUSTOMER });
    });

    it("answers the server's own refusal for a host no surface is bound to", async () => {
        const refusal = { detail: "This address is not one this product answers at.", code: "surface_unknown_host", remedies: [] };
        const world = await backend(404, refusal);
        started.server = world.server;
        const answer = await (await asker(world.origin))("nowhere.localhost");
        expect(answer).toEqual({ kind: "refused", refusal: { kind: "registry", refusal } });
    });

    it("refuses a 200 that is not the answer, never casts it", async () => {
        const world = await backend(200, { surface: "" });
        started.server = world.server;
        expect((await (await asker(world.origin))("localhost")).kind).toBe("refused");
    });

    it("a backend that is not there is a transport failure, never a thrown promise", async () => {
        const answer = await (await asker("http://127.0.0.1:9"))("localhost");
        expect(answer.kind === "refused" && answer.refusal.kind).toBe("transport");
    });
});

describe("the proxy's origin is supplied, never defaulted", () => {
    it.each(["", "  "])("an unset DJANGO_ORIGIN (%j) refuses at load, naming how to supply this checkout's own", async (value) => {
        vi.stubEnv("DJANGO_ORIGIN", value);
        vi.resetModules();
        await expect(import("@/api/surface-server")).rejects.toThrow(/DJANGO_ORIGIN is unset.*serve\.sh --print-port/);
    });
});
