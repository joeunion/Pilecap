import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { REFUSAL_WORDS } from "@/copy/refusals";
import { RefusalPanel } from "@/kit/refusal-panel";
import { STAFF_SURFACE } from "@/kit/routes";
import type { Refusal } from "@/kit/state";

afterEach(cleanup);

const REGISTRY: Refusal = {
    kind: "registry",
    refusal: { code: "conflict", detail: "This widget is still in use.", remedies: [{ label: "Ask an admin", destination: "self:ask" }] },
};
const TRANSPORT: Refusal = { kind: "transport", code: "network_unreachable", detail: "This page could not reach the server. Nothing was sent." };

function firstLine(container: HTMLElement): string | null | undefined {
    return container.querySelector('[role="alert"] p')?.textContent;
}

describe("the panel's words default from the one declaration", () => {
    it("a registry refusal handed no words opens with the default refused line and heads its remedies with the default heading", () => {
        const { container } = render(<RefusalPanel refusal={REGISTRY} surface={STAFF_SURFACE} />);
        expect(firstLine(container)).toBe(REFUSAL_WORDS.errorLabel);
        expect(container.textContent).toContain(REFUSAL_WORDS.remedies);
    });

    it("a transport refusal handed no words opens with the default did-not-answer line", () => {
        const { container } = render(<RefusalPanel refusal={TRANSPORT} surface={STAFF_SURFACE} />);
        expect(firstLine(container)).toBe(REFUSAL_WORDS.transportLabel);
    });

    it("an act's refused word is the first line, for either member of the union", () => {
        for (const refusal of [REGISTRY, TRANSPORT]) {
            const { container } = render(<RefusalPanel refusal={refusal} refused="Couldn't archive" surface={STAFF_SURFACE} />);
            expect(firstLine(container)).toBe("Couldn't archive");
            cleanup();
        }
    });

    it("an act whose word is absent falls back to the default, never to nothing", () => {
        const { container } = render(<RefusalPanel refusal={REGISTRY} refused={undefined} surface={STAFF_SURFACE} />);
        expect(firstLine(container)).toBe(REFUSAL_WORDS.errorLabel);
    });

    it("a surface's own voice replaces only the words it names", () => {
        const { container } = render(<RefusalPanel refusal={REGISTRY} words={{ label: "Your access here ended" }} surface={STAFF_SURFACE} />);
        expect(firstLine(container)).toBe("Your access here ended");
        expect(container.textContent).toContain(REFUSAL_WORDS.remedies);
    });
});

describe("the panel renders the server's words verbatim and none of its own (patterns.md §15)", () => {
    it("a registry refusal: the server's fact, its code and every remedy's label, verbatim, in one alert", () => {
        const { container } = render(<RefusalPanel refusal={REGISTRY} surface={STAFF_SURFACE} />);
        expect(container.querySelectorAll('[role="alert"]')).toHaveLength(1);
        const text = container.textContent ?? "";
        expect(text).toContain("This widget is still in use.");
        expect(container.querySelector("code")?.textContent).toBe("conflict");
        expect(text).toContain("Ask an admin");
        expect(text).not.toContain("self:ask");
        expect(text).not.toContain("undefined");
    });

    it("a transport failure: this client's own sentence and code, and no remedies heading, because no response existed", () => {
        const { container } = render(<RefusalPanel refusal={TRANSPORT} surface={STAFF_SURFACE} />);
        const text = container.textContent ?? "";
        expect(text).toContain(TRANSPORT.kind === "transport" ? TRANSPORT.detail : "");
        expect(container.querySelector("code")?.textContent).toBe("network_unreachable");
        expect(text).not.toContain(REFUSAL_WORDS.remedies);
        expect(text).not.toContain("undefined");
    });

    it("a registry refusal with no remedies draws no remedies heading", () => {
        const bare: Refusal = { kind: "registry", refusal: { code: "not_found", detail: "Nothing here." } };
        const { container } = render(<RefusalPanel refusal={bare} surface={STAFF_SURFACE} />);
        expect(container.textContent).not.toContain(REFUSAL_WORDS.remedies);
        expect(container.querySelector("ul")).toBeNull();
    });
});
