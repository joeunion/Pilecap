import { describe, expect, it } from "vitest";

import type { Answer } from "@/api/client";
import { booted } from "@/api/surface";

const UNDECLARED = { surface: "staff", screens: "*", tenant_rule: "addressed" };
const CUSTOMER = { surface: "customer", screens: ["/portal"], tenant_rule: "membership" };

describe("the boot question's answer is read, never cast", () => {
    it.each([
        ["an undeclared product", UNDECLARED],
        ["a declared surface", CUSTOMER],
    ])("answers %s verbatim", (_name, body) => {
        expect(booted({ kind: "ok", data: body })).toEqual({ kind: "ok", data: body });
    });

    it("a refusal passes through untouched — it is not the shape check's to judge", () => {
        const refused: Answer<unknown> = {
            kind: "refused",
            refusal: { kind: "transport", code: "network_unreachable", detail: "This page could not reach the server." },
        };
        expect(booted(refused)).toBe(refused);
    });

    it.each([
        ["no key", { screens: "*", tenant_rule: "addressed" }],
        ["an empty key", { surface: "", screens: "*", tenant_rule: "addressed" }],
        ["screens neither a star nor a list", { surface: "staff", screens: "all", tenant_rule: "addressed" }],
        ["a screen that is not a path", { surface: "staff", screens: [3], tenant_rule: "addressed" }],
        ["a tenant rule the server has no word for", { surface: "staff", screens: "*", tenant_rule: "header" }],
    ])("a 200 whose body is not the answer (%s) is refused, not cast", (_name, body) => {
        const answer = booted({ kind: "ok", data: body });
        expect(answer.kind === "refused" && answer.refusal.kind === "transport" && answer.refusal.code).toBe("network_unreachable");
    });
});
