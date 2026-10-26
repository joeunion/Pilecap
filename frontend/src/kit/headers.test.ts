import { afterEach, describe, expect, it, vi } from "vitest";

type HeaderRule = { source: string; headers: { key: string; value: string }[] };

/** The config's `headers()` rules, loaded with the origin the module requires, in `mode`. */
async function headerRules(mode = "production"): Promise<HeaderRule[]> {
    vi.resetModules();
    vi.stubEnv("DJANGO_ORIGIN", "http://127.0.0.1:9");
    vi.stubEnv("NODE_ENV", mode);
    const config = (await import("../../next.config")).default;
    expect(config.headers, "next.config.ts exports no headers()").toBeTypeOf("function");
    return (await config.headers!()) as HeaderRule[];
}

/** The headers the every-route rule sets in `mode`, by lower-cased name. */
async function everyRoute(mode = "production"): Promise<Map<string, string>> {
    const rule = (await headerRules(mode)).find((row) => row.source === "/:path*");
    expect(rule, "no headers() rule matches every route").toBeDefined();
    return new Map(rule!.headers.map(({ key, value }) => [key.toLowerCase(), value]));
}

/** A CSP value as directive name -> its sources. */
function directives(policy: string): Map<string, string[]> {
    const parsed = policy
        .split(";")
        .map((part) => part.trim().split(/\s+/))
        .filter((words) => words[0] !== undefined && words[0] !== "")
        .map(([name, ...sources]) => [name!, sources] as const);
    return new Map(parsed);
}

afterEach(() => {
    vi.unstubAllEnvs();
});

describe("the frontend's response headers", () => {
    it("sets the five fixed headers on every route", async () => {
        const headers = await everyRoute();
        expect(headers.get("x-content-type-options")).toBe("nosniff");
        expect(headers.get("referrer-policy")).toBe("strict-origin-when-cross-origin");
        expect(headers.get("x-frame-options")).toBe("DENY");
        expect(headers.get("cross-origin-opener-policy")).toBe("same-origin");
        expect(headers.get("permissions-policy")).toBe("camera=(), microphone=(), geolocation=()");
    });

    it("never sets HSTS, which Caddy owns", async () => {
        const named = (await headerRules()).flatMap((rule) => rule.headers.map(({ key }) => key.toLowerCase()));
        expect(named).not.toContain("strict-transport-security");
    });

    it("enforces the CSP in production, with the exact directive string", async () => {
        const headers = await everyRoute("production");
        expect(headers.has("content-security-policy-report-only")).toBe(false);
        expect(headers.get("content-security-policy")).toBe(
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self' ws: wss:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        );
    });

    it("enforces the same CSP under next dev, plus the eval its bundler needs", async () => {
        const headers = await everyRoute("development");
        expect(headers.has("content-security-policy-report-only")).toBe(false);
        expect(headers.get("content-security-policy")).toBe(
            "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; connect-src 'self' ws: wss:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        );
    });

    it("takes the production policy for any mode that is not development", async () => {
        expect((await everyRoute("test")).get("content-security-policy")).toBe(
            (await everyRoute("production")).get("content-security-policy"),
        );
    });

    it("agrees with the backend on framing", async () => {
        // The one declared copy of `config/settings/base.py` X_FRAME_OPTIONS = "DENY" and
        // `config/settings/production.py` CONTENT_SECURITY_POLICY "frame-ancestors": ["'none'"].
        const BACKEND_X_FRAME_OPTIONS = "DENY";
        const BACKEND_FRAME_ANCESTORS = ["'none'"];
        const headers = await everyRoute();
        expect(headers.get("x-frame-options")).toBe(BACKEND_X_FRAME_OPTIONS);
        expect(directives(headers.get("content-security-policy") ?? "").get("frame-ancestors")).toEqual(
            BACKEND_FRAME_ANCESTORS,
        );
    });
});
