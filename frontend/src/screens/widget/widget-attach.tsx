// golden: attach begin
// patterns: §6, §10, §13, §14, §15
"use client";
// golden: attach end

/**
 * EXAMPLE — the worked Widget's attachments: notes, files and tags on any
 * noun (the attach road; patterns.md §10, the card, and §6, the tag row under
 * the lede). A product copies it for its own noun.
 *
 * **Notes** is a card in main, before History: its rows *⟨body⟩ · ⟨day⟩*,
 * newest first, and *Add a note* at its foot, which opens an inline field
 * whose own primary is *Add*. **Files** is the card after Notes, over the
 * files door narrowed to this row (`subject`): its rows *⟨file name⟩ ·
 * ⟨day⟩*, each carrying *Archive* where the file's own answer offers it, and
 * *Add a file* at its foot. **Tags** is a row directly under the head's lede:
 * each tag a word with its ×, named *Remove tag ⟨name⟩* (a tag coming off is
 * not a noun leaving the book), and *Add a tag*, which opens a chooser of the
 * existing tags that also adds the typed word.
 *
 * WHO MAY ATTACH is the owners' answer, never the row's: a note or a tag goes
 * on any row the reader can see, and a file asks its list's `create`. The
 * route hands the press where the answer is yes; with no press the act is
 * absent. On an archived or merged row the record draws none of it.
 *
 * TWO HONEST ABSENCES: a note's row names no author and carries no act of its
 * own — the wire's note carries the author's address (never a reader's word)
 * and no per-note answer, so *Edit* and *Archive* on a note are not drawn;
 * and the list's `?tag=` chip is not drawn, because the list read takes no
 * tag narrowing.
 *
 * It renders and never fetches: the route reads `/notes/?subject=`,
 * `/files/?subject=` and the tag chooser's `/tags/?q=`, and writes.
 */

// golden: attach begin
import { type ReactNode, type Ref, type RefObject, useEffect, useRef, useState } from "react";

import { WIDGET_COPY as C, removeTagLabel } from "@/copy/widget";
import { RefusalPanel } from "@/screens/refusal-panel";
import type { Refusal, SurfaceState } from "@/screens/state";
import { type Act, actsFor, attachAct, type Road } from "@/screens/verbs";
import { Card, dayOf, type Note, StillLine, type StoredFile, type Tag } from "@/screens/widget/parts";

/** One attach kind's press: its read, the add, the add at work, and the last refusal. */
type AttachPart<T, A> = {
    readonly state: SurfaceState<readonly T[]>;
    readonly onAdd: (value: A) => Promise<boolean>;
    readonly busy?: boolean;
    readonly refused?: Refusal | null;
};

/** What the route hands the record for attach: each kind it can take. A kind with no press is absent. */
export type AttachPress = {
    readonly notes?: AttachPart<Note, string>;
    /** Files: `onAdd` only where the files list answered `create` for this hat. */
    readonly files?: Omit<AttachPart<StoredFile, File>, "onAdd"> & {
        readonly onAdd?: (file: File) => Promise<boolean>;
        readonly onArchive?: (id: string) => void;
    };
    readonly tags?: {
        /** The existing tags the chooser offers for what is typed. */
        readonly choices: SurfaceState<readonly Tag[]>;
        readonly onSearch?: (q: string) => void;
        /** Put a tag on: an existing one by id, or the typed word. */
        readonly onAdd: (tag: { readonly id: string } | { readonly name: string }) => Promise<boolean>;
        readonly onRemove: (tagId: string) => void;
        readonly busy?: boolean;
        readonly refused?: Refusal | null;
    };
};

/** Which inline field is open: one at a time, so a face never shows two primaries. */
export type Adding = "note" | "file" | "tag" | null;

/** The record's attach state: which field is open, and where focus lands after an add. */
export function useAdding() {
    const [adding, setAdding] = useState<Adding>(null);
    return { adding, open: (kind: Adding) => setAdding(kind), close: () => setAdding(null) };
}

/** The Notes card: rows newest first, *Add a note* at its foot, the inline field with its one *Add*. */
export function NotesCard({ road, part, adding }: { readonly road: Road; readonly part: NonNullable<AttachPress["notes"]>; readonly adding: ReturnType<typeof useAdding> }) {
    const act = attachAct(road, "note");
    const first = useRef<HTMLLIElement>(null);
    const landing = useLandingOnFirst(part.state, first);
    return (
        <Card title={C.notesTitle}>
            <CardRows
                state={part.state}
                loading={C.loadingNotes}
                empty={C.notesEmpty}
                rows={(notes) =>
                    notes.map((note, index) => (
                        <li key={note.id} tabIndex={-1} ref={index === 0 ? first : undefined}>
                            {note.body} · {dayOf(note.created_at)}
                        </li>
                    ))
                }
            />
            {act === null ? null : (
                <AddFoot
                    act={act}
                    kind="note"
                    adding={adding}
                    busy={part.busy === true}
                    refused={part.refused ?? null}
                    field={(ref, value, set) => <textarea ref={ref as Ref<HTMLTextAreaElement>} aria-label={act.label} value={value} onChange={(event) => set(event.target.value)} />}
                    onAdd={async (value) => {
                        landing.arm();
                        return part.onAdd(value);
                    }}
                />
            )}
        </Card>
    );
}

/** The Files card: the files on this row, each with its own *Archive* where offered; *Add a file* at its foot. */
export function FilesCard({ road, part, adding }: { readonly road: Road; readonly part: NonNullable<AttachPress["files"]>; readonly adding: ReturnType<typeof useAdding> }) {
    const act = part.onAdd === undefined ? null : attachAct(road, "file");
    const first = useRef<HTMLLIElement>(null);
    const landing = useLandingOnFirst(part.state, first);
    return (
        <Card title={C.filesTitle}>
            <CardRows
                state={part.state}
                loading={C.loadingFiles}
                empty={C.filesEmpty}
                rows={(files) =>
                    files.map((file, index) => (
                        <li key={file.id} tabIndex={-1} ref={index === 0 ? first : undefined} className="widget-attached">
                            <span>
                                {file.filename} · {dayOf(file.created_at)}
                            </span>
                            {part.onArchive === undefined
                                ? null
                                : actsFor({ allowed_acts: file.allowed_acts ?? [] }, road, "card-head").map((archive: Act) => (
                                      <button key={archive.verb} type="button" className="widget-act" {...archive.attrs} onClick={() => part.onArchive?.(file.id)}>
                                          {archive.label}
                                      </button>
                                  ))}
                        </li>
                    ))
                }
            />
            {act === null ? null : (
                <AddFoot
                    act={act}
                    kind="file"
                    adding={adding}
                    busy={part.busy === true}
                    refused={part.refused ?? null}
                    field={(ref, _value, _set, pick) => (
                        <input ref={ref as Ref<HTMLInputElement>} type="file" aria-label={act.label} onChange={(event) => pick(event.target.files?.[0] ?? null)} />
                    )}
                    onAdd={async (_value, file) => {
                        if (file === null || part.onAdd === undefined) return false;
                        landing.arm();
                        return part.onAdd(file);
                    }}
                />
            )}
        </Card>
    );
}

/**
 * The tag row, directly under the head's lede: each tag its word and its ×
 * (*Remove tag ⟨name⟩*), then *Add a tag*, which opens the chooser in place —
 * the existing tags matching what is typed, each one press, and *Add* for the
 * typed word. Its refusal sits directly under the row.
 */
export function TagRow({
    road,
    tags,
    part,
    adding,
    live,
}: {
    readonly road: Road;
    /** A row that is not live (archived, merged) wears its tags and offers no act on them. */
    readonly live: boolean;
    readonly tags: readonly Tag[];
    readonly part: NonNullable<AttachPress["tags"]>;
    readonly adding: ReturnType<typeof useAdding>;
}) {
    const act = live ? attachAct(road, "tag") : null;
    const [q, setQ] = useState("");
    const field = useRef<HTMLInputElement>(null);
    const open = adding.adding === "tag" && act !== null;
    useEffect(() => {
        if (open) field.current?.focus();
    }, [open]);
    const choices = part.choices.kind === "ready" ? part.choices.data.filter((tag) => !tags.some((on) => on.id === tag.id)) : [];
    // An added tag lands focus on its own × (the tag's one act): armed at the
    // press with the tags already on, spent when the re-read brings the new one.
    const removes = useRef(new Map<string, HTMLButtonElement>());
    const before = useRef<ReadonlySet<string> | null>(null);
    const ids = tags.map((tag) => tag.id).join(" ");
    useEffect(() => {
        const armed = before.current;
        if (armed === null) return;
        const added = ids.split(" ").find((id) => id !== "" && !armed.has(id));
        if (added === undefined) return;
        before.current = null;
        removes.current.get(added)?.focus();
    }, [ids]);
    const addTag = async (tag: { readonly id: string } | { readonly name: string }) => {
        before.current = new Set(tags.map((on) => on.id));
        const added = await part.onAdd(tag);
        if (!added) before.current = null;
        return added;
    };
    return (
        <>
            <div data-tags="" className="widget-tags">
                {tags.map((tag) => (
                    <span key={tag.id} className="widget-tag">
                        {tag.name}
                        {act === null ? null : (
                            <button
                                type="button"
                                className="widget-tag-remove"
                                aria-label={removeTagLabel(tag.name)}
                                ref={(el) => {
                                    if (el === null) removes.current.delete(tag.id);
                                    else removes.current.set(tag.id, el);
                                }}
                                onClick={() => part.onRemove(tag.id)}
                            >
                                ×
                            </button>
                        )}
                    </span>
                ))}
                {act === null ? null : (
                    <button
                        type="button"
                        className="widget-act"
                        {...act.attrs}
                        aria-busy={part.busy === true ? "true" : undefined}
                        aria-expanded={open ? "true" : "false"}
                        onClick={() => (open ? field.current?.focus() : adding.open("tag"))}
                    >
                        {part.busy === true ? act.busy : act.label}
                    </button>
                )}
            </div>
            {open ? (
                <div className="widget-adding">
                    <input
                        ref={field}
                        type="search"
                        className="widget-search"
                        aria-label={act.label}
                        value={q}
                        onChange={(event) => {
                            setQ(event.target.value);
                            part.onSearch?.(event.target.value);
                        }}
                    />
                    {choices.map((tag) => (
                        <button
                            key={tag.id}
                            type="button"
                            className="widget-pick"
                            onClick={async () => {
                                if (await addTag({ id: tag.id })) adding.close();
                            }}
                        >
                            {tag.name}
                        </button>
                    ))}
                    {q.trim() === "" ? null : (
                        <button
                            type="button"
                            className="widget-act widget-primary"
                            data-weight="primary"
                            onClick={async () => {
                                if (await addTag({ name: q.trim() })) {
                                    setQ("");
                                    adding.close();
                                }
                            }}
                        >
                            {C.addAct}
                        </button>
                    )}
                </div>
            ) : null}
            {part.refused === null || part.refused === undefined || act === null ? null : (
                <div className="widget-refusal-seat">
                    <RefusalPanel refusal={part.refused} seat="tag-row" words={{ label: act.words.refused, remedies: C.remedies }} />
                </div>
            )}
        </>
    );
}

/** A card's read: still rows, its empty line, the refusal inside it, or its rows. */
function CardRows<T>({
    state,
    loading,
    empty,
    rows,
}: {
    readonly state: SurfaceState<readonly T[]>;
    readonly loading: string;
    readonly empty: string;
    readonly rows: (items: readonly T[]) => ReactNode;
}) {
    if (state.kind === "loading") {
        return (
            <div aria-busy="true" aria-live="polite">
                <p className="widget-quiet">{loading}</p>
                <StillLine />
                <StillLine />
            </div>
        );
    }
    if (state.kind === "empty") return <p className="widget-quiet">{empty}</p>;
    if (state.kind === "error") return <RefusalPanel refusal={state.refusal} words={{ label: C.errorLabel, remedies: C.remedies }} />;
    return <ol className="widget-history">{rows(state.data)}</ol>;
}

/**
 * A card's foot: its attach act (ghost), and when pressed the inline field
 * with its one primary *Add*; the refusal sits in the card above the foot,
 * *Couldn't add* first, the act alive. After an add, focus lands on the new
 * row.
 */
function AddFoot({
    act,
    kind,
    adding,
    busy,
    refused,
    field,
    onAdd,
}: {
    readonly act: Act;
    readonly kind: "note" | "file";
    readonly adding: ReturnType<typeof useAdding>;
    readonly busy: boolean;
    readonly refused: Refusal | null;
    readonly field: (ref: Ref<HTMLElement>, value: string, set: (value: string) => void, pick: (file: File | null) => void) => ReactNode;
    readonly onAdd: (value: string, file: File | null) => Promise<boolean>;
}) {
    const open = adding.adding === kind;
    const [value, setValue] = useState("");
    const [file, setFile] = useState<File | null>(null);
    const ref = useRef<HTMLElement>(null);
    useEffect(() => {
        if (open) ref.current?.focus();
    }, [open]);
    return (
        <>
            {refused === null ? null : (
                <div className="widget-refusal-seat">
                    <RefusalPanel refusal={refused} seat="card-foot" words={{ label: act.words.refused, remedies: C.remedies }} />
                </div>
            )}
            {open ? (
                <div className="widget-adding">
                    {field(ref, value, setValue, setFile)}
                    {value.trim() === "" && file === null ? null : (
                        <button
                            type="button"
                            className="widget-act widget-primary"
                            data-weight="primary"
                            aria-busy={busy ? "true" : undefined}
                            onClick={async () => {
                                if (await onAdd(value.trim(), file)) {
                                    setValue("");
                                    setFile(null);
                                    adding.close();
                                }
                            }}
                        >
                            {busy ? act.busy : C.addAct}
                        </button>
                    )}
                </div>
            ) : null}
            <div className="widget-card-foot">
                <button type="button" className="widget-act" {...act.attrs} onClick={() => (open ? ref.current?.focus() : adding.open(kind))}>
                    {act.label}
                </button>
            </div>
        </>
    );
}

/** After an add, focus lands on the new row — the first, newest first — when the re-read brings it. */
function useLandingOnFirst<T extends { readonly id: string }>(state: SurfaceState<readonly T[]>, first: RefObject<HTMLLIElement | null>) {
    const armed = useRef<string | null | undefined>(undefined);
    const top = state.kind === "ready" ? (state.data[0]?.id ?? null) : null;
    useEffect(() => {
        if (armed.current === undefined || top === armed.current) return;
        armed.current = undefined;
        first.current?.focus();
    }, [top, first]);
    return {
        arm: () => {
            armed.current = top;
        },
    };
}
// golden: attach end
