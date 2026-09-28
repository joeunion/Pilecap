import { fireEvent, render, screen } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import { DIALOG_COPY } from "@/copy/dialog";
import { Dialog } from "@/primitives/dialog";

// jsdom draws a <dialog> but implements neither showModal() nor close(); the
// primitive calls both, so the test gives the element the two methods it needs
// and nothing else. The rendered modal behaviour is a browser fact.
const proto = HTMLDialogElement.prototype as unknown as Record<string, unknown>;
const saved = { showModal: proto.showModal, close: proto.close };

beforeAll(() => {
    proto.showModal = function (this: HTMLDialogElement) {
        this.setAttribute("open", "");
    };
    proto.close = function (this: HTMLDialogElement) {
        this.removeAttribute("open");
    };
});

afterAll(() => {
    proto.showModal = saved.showModal;
    proto.close = saved.close;
});

describe("the one dialog", () => {
    it("draws one head with the one dismiss, the body, and a foot of acts only", () => {
        const onDismiss = vi.fn();
        render(
            <Dialog open title="Rename the branch" onDismiss={onDismiss} foot={<button type="button">Rename</button>}>
                <p>The body.</p>
            </Dialog>,
        );
        const sheet = document.querySelector("dialog");
        expect(sheet).not.toBeNull();
        expect(sheet?.hasAttribute("open")).toBe(true);
        expect(screen.getByRole("heading", { name: "Rename the branch" })).toBeDefined();

        const head = sheet?.querySelector("header");
        expect(head?.querySelectorAll("button")).toHaveLength(1);
        expect(head?.textContent).toContain(DIALOG_COPY.dismiss);

        const foot = sheet?.querySelector("footer");
        expect(foot?.textContent).toBe("Rename");
        expect(foot?.textContent).not.toContain(DIALOG_COPY.dismiss);
    });

    it("the head's dismiss and Escape both ask the owner, and the owner closes it", () => {
        const onDismiss = vi.fn();
        const { rerender } = render(
            <Dialog open title="A sheet" onDismiss={onDismiss}>
                <p>The body.</p>
            </Dialog>,
        );
        fireEvent.click(screen.getByRole("button", { name: DIALOG_COPY.dismiss }));
        const sheet = document.querySelector("dialog") as HTMLDialogElement;
        fireEvent(sheet, new Event("cancel", { cancelable: true }));
        expect(onDismiss).toHaveBeenCalledTimes(2);
        expect(sheet.hasAttribute("open")).toBe(true);

        rerender(
            <Dialog open={false} title="A sheet" onDismiss={onDismiss}>
                <p>The body.</p>
            </Dialog>,
        );
        expect(sheet.hasAttribute("open")).toBe(false);
        expect(document.querySelector("footer")).toBeNull();
    });
});
