import type { NextConfig } from "next";

// THE PROXY, AND THE THREE LINES THAT ARE NOT DEFAULTS. Each one is a defect
// this repository's frontend conventions were written from
// (`.claude/skills/fe-conventions/SKILL.md` §6); none of them announces itself
// when it is wrong, which is why they are pinned here with the argument beside
// them rather than left to a later reader's judgement.
//
// THE ONE PLACE OUTSIDE `src/api/` THAT NAMES THE BACKEND ORIGIN, and it is the
// declared exception to Law 2 rather than a hole in it: a rewrite is where the
// origin is *defined*, so the seam can be same-origin and carry the session
// cookie without a CORS story at all. No component, route or test may name it.
// Exported for the one other reader, and it is inside the seam: the server-side
// surface ask (`src/api/surface-server.ts`, over `node:http`: Node's fetch drops a caller-set Host) — one spelling.
//
// REQUIRED, AND REFUSED WHEN UNSET — never defaulted. The backend's port is
// derived per checkout (`./scripts/serve.sh --print-port`), so no constant here
// can name it, and a default that names a port nobody bound is a proxy to
// nothing that says nothing. Deriving it here instead would run a checkout's
// shell script wherever this module loads — the build, `next start` on a host
// with no checkout, and the server-side surface ask above — so the value is the
// caller's to supply, and this module says so in one sentence when it is not.
export const DJANGO_ORIGIN = requiredOrigin(process.env.DJANGO_ORIGIN);

/** The backend origin the proxy points at, or a refusal naming how to supply it. */
function requiredOrigin(value: string | undefined): string {
    if (value === undefined || value.trim() === "") {
        throw new Error(
            "DJANGO_ORIGIN is unset, so the proxy has no backend to point at: export DJANGO_ORIGIN=http://127.0.0.1:$(./scripts/serve.sh --print-port) from the repository root (this checkout's own backend), or the origin of the backend this build serves.",
        );
    }
    return value;
}

// The version segment is `config/urls.py`'s, and the client takes it verbatim
// rather than composing one (P16 ruling 1: rule 32 translates as CONSUMPTION).
const API_PREFIX = "/api/v1";
const SOCKET_PREFIX = "/ws";

// ENFORCED (architecture.md's CORS / CSRF / CSP row; `frontend/src/kit/headers.test.ts` pins the string):
// every widening past 'self' is one the rendered surfaces were measured to need, and no other is added:
//   script-src 'unsafe-inline' — the App Router's inline `self.__next_f.push` hydration payload scripts.
//   style-src 'unsafe-inline' — React-rendered `style=` attributes and Next's built-in not-found/error
//     `<style>` element and attributes.
//   'unsafe-eval' — `next dev` ONLY (its bundler's eval); every other mode takes the production set.
// No `img-src data:` and no report endpoint.
const DEVELOPMENT = process.env.NODE_ENV === "development";
const CONTENT_SECURITY_POLICY = [
    "default-src 'self'",
    DEVELOPMENT ? "script-src 'self' 'unsafe-inline' 'unsafe-eval'" : "script-src 'self' 'unsafe-inline'",
    "style-src 'self' 'unsafe-inline'",
    "connect-src 'self' ws: wss:",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
].join("; ");

// HSTS is Caddy's (`deploy/Caddyfile`); framing is the backend's `X_FRAME_OPTIONS`.
const SECURITY_HEADERS = [
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
    { key: "X-Frame-Options", value: "DENY" },
    { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
    { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
    { key: "Content-Security-Policy", value: CONTENT_SECURITY_POLICY },
];

const nextConfig: NextConfig = {
    // NEXT 16 WRITES `AGENTS.md` AND `CLAUDE.md` INTO THIS DIRECTORY ON THE
    // FIRST `next dev` UNLESS THIS IS OFF, and in this repository that is not a
    // convenience, it is a second authority file appearing where the first one
    // already says what the rules are. A generated `CLAUDE.md` in `frontend/` would
    // be read by every agent that opens this directory, would say things nobody
    // here decided, and would go stale the moment Next's template changed —
    // which is the exact class `CLAUDE.md` opens by refusing. `README.md` and
    // `.claude/skills/fe-conventions/SKILL.md` are the two files that answer
    // "how do I write anything here", and there are deliberately no others.
    agentRules: false,

    // React 19 StrictMode double-invokes effects in development. It is ON on
    // purpose: the bootstrap that ran twice and the cleanup that discarded the
    // answer (§6.3, §6.4) are only visible with it on, and a template that
    // turned it off would ship every product that mistake pre-hidden.
    reactStrictMode: true,

    // The deployed face is `.next/standalone/server.js` in the `frontend`
    // image (`Dockerfile`), a server with only the modules it traces; `next dev`
    // ignores it.
    output: "standalone",

    // §6.1 — the 308 that ate the request. Next's default answers
    // `/api/v1/organizations/` with a 308 BEFORE any rewrite runs, and a
    // browser following that redirect drops the method and the body. Django's
    // resource paths all end in a slash, so every proxied call would be a
    // redirect pair.
    skipTrailingSlashRedirect: true,

    // §6.6 — the page that rendered perfectly and never hydrated. The page is
    // served through the proxy on a different origin than `next dev` itself;
    // with this unset the development server refuses the hydration assets and
    // refuses them QUIETLY. Both spellings, because to a browser they are two
    // different origins.
    allowedDevOrigins: ["127.0.0.1", "localhost"],

    async headers() {
        return [{ source: "/:path*", headers: SECURITY_HEADERS }];
    },

    async rewrites() {
        // §6.2 — the rewrite that ate the slash. The segment form `:path*`
        // splits on `/` and rejoins, silently dropping a trailing empty
        // segment, so `/api/v1/organizations/` arrives at Django as
        // `/api/v1/organizations` and django-ninja answers its own 404. The
        // regex form captures the rest of the path verbatim, slash included.
        return [
            {
                source: `${API_PREFIX}/:path(.*)`,
                destination: `${DJANGO_ORIGIN}${API_PREFIX}/:path`,
            },
            // The socket door (`ws/events/`), same-origin so the session cookie rides the upgrade.
            {
                source: `${SOCKET_PREFIX}/:path(.*)`,
                destination: `${DJANGO_ORIGIN}${SOCKET_PREFIX}/:path`,
            },
        ];
    },
};

export default nextConfig;
