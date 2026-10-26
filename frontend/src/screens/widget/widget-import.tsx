// golden: import begin
// patterns: §5, §13, §14, §15, §17
"use client";
// golden: import end

/**
 * EXAMPLE — the worked Widget's import page: upload, check, preview, apply
 * (the Import road; patterns.md §5, the list page head, and §17, bands). A
 * product copies it for its own noun.
 *
 * ONE PAGE, ITS STATES READ FROM THE RUN ROW (the route polls the run — the
 * work is the server's workflow; the page only shows it): *choose* (the file
 * field, the columns the file carries, and *Import*) → *checking* (*Checking
 * ⟨file⟩…*, still) → *previewed* (the counts line, then each refused row by
 * its number with the server's sentence, then ONE primary *Import ⟨n⟩
 * widgets*, n what the apply will write — none when it would write nothing)
 * → *importing* (the same button, *Importing…*, alive) → *imported*
 * (*Imported ⟨n⟩ widgets on ⟨day⟩.*, the list a link). The same file again
 * lands on its run: *This file was imported on ⟨day⟩.* A file refused whole
 * (`import_invalid`) sits under the head, the file field alive.
 *
 * TWO HONEST ABSENCES: the run carries no progress count, so *importing* is
 * the apply's busy word on its own button rather than *⟨n⟩ of ⟨m⟩ rows*; and
 * the importer's row schema is not in the document, so the columns are the
 * copy module's words for it.
 *
 * It renders and never fetches (fe-conventions §7: polling a run row is a read
 * with an interval, the route's; no retry lives here).
 */

// golden: import begin
import { useEffect, useRef, useState } from "react";

import {
    WIDGET_COPY as C,
    checkingSentence,
    importApplyLabel,
    importColumnsSentence,
    importCountsLine,
    importedSentence,
    importPageTitle,
    importRepeatedSentence,
    nothingToImportSentence,
    refusedRowSentence,
} from "@pilecap/copy/widget";
import type { components } from "@/api/generated/schema";
import { RefusalPanel } from "@pilecap/ui/refusal-panel";
import { pathFor, STAFF_SURFACE } from "@pilecap/ui/routes";
import type { Refusal, SurfaceState } from "@pilecap/ui/state";
import { unhandledState } from "@pilecap/ui/state";
import { importActs } from "@pilecap/ui/verbs";
import { StillLine } from "@pilecap/ui/still-line";
import { dayOf } from "@/screens/widget/parts";
import { ROAD } from "@/screens/widget/road";
import "@/screens/widget/widget-face.css";

/** The run row and one of its rows, the imports door's own shapes. */
export type ImportRun = components["schemas"]["DjbImportOut"];
export type ImportRow = components["schemas"]["DjbImportRowOut"];

/** What the page shows: the run (none yet while choosing), its refused rows, and whether the file was already imported. */
export type ImportView = {
    readonly run: ImportRun | null;
    readonly refusedRows: readonly ImportRow[];
    readonly repeated?: boolean;
};

/** What the route hands the page: stage the chosen file, apply the previewed run, and the last refusal. */
export type ImportPress = {
    readonly onStage: (file: File) => void;
    readonly onApply: () => void;
    readonly busy?: "stage" | "apply" | null;
    readonly refused?: Refusal | null;
};

export function WidgetImport({ state, press }: { readonly state: SurfaceState<ImportView>; readonly press?: ImportPress }) {
    const list = pathFor("widget-list", {}, undefined, STAFF_SURFACE);
    return (
        <main className="widget-page widget-page-prose">
            <p className="widget-crumb-line">
                {list === null ? (
                    C.title
                ) : (
                    <a href={list} className="widget-crumb">
                        {C.title}
                    </a>
                )}
            </p>
            <h1 className="widget-title">{importPageTitle()}</h1>
            {body(state, press)}
        </main>
    );
}

function body(state: SurfaceState<ImportView>, press: ImportPress | undefined) {
    switch (state.kind) {
        case "loading":
            return (
                <div aria-busy="true" aria-live="polite">
                    <p className="widget-quiet">{C.loadingImport}</p>
                    <StillLine />
                    <StillLine tall />
                </div>
            );
        case "empty":
            // No run yet: choose a file. (A file with no rows is a run whose counts are all 0.)
            return <Choose press={press} />;
        case "error":
            // A file refused whole: the notice under the head, the file field alive.
            return <Choose press={press} refused={state.refusal} />;
        case "ready":
            return <Run view={state.data} press={press} />;
    }
    return unhandledState(state);
}

/** *choose*: the file field, the columns, *Import*; a whole-file refusal under the head. */
function Choose({ press, refused }: { readonly press: ImportPress | undefined; readonly refused?: Refusal | null }) {
    const acts = importActs(ROAD);
    const [file, setFile] = useState<File | null>(null);
    const notice = refused ?? press?.refused ?? null;
    if (acts === null) return null;
    return (
        <>
            {notice === null ? null : (
                <div className="widget-refusal-seat">
                    <RefusalPanel surface={STAFF_SURFACE} refusal={notice} seat="list-head" refused={acts.stage.words.refused} />
                </div>
            )}
            <p className="widget-quiet">{importColumnsSentence()}</p>
            {press === undefined ? null : (
                <div className="widget-adding">
                    <input type="file" accept=".csv,text/csv" aria-label={importPageTitle()} onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
                    <button
                        type="button"
                        className="widget-act widget-primary"
                        {...acts.stage.attrs}
                        aria-busy={press.busy === "stage" ? "true" : undefined}
                        onClick={() => {
                            if (file !== null) press.onStage(file);
                        }}
                    >
                        {press.busy === "stage" ? acts.stage.busy : acts.stage.label}
                    </button>
                </div>
            )}
        </>
    );
}

/** The run's states: checking, previewed, importing, imported — and the file already imported. */
function Run({ view, press }: { readonly view: ImportView; readonly press: ImportPress | undefined }) {
    const { run } = view;
    const acts = importActs(ROAD);
    const counts = useRef<HTMLParagraphElement>(null);
    const previewed = run?.status === "previewed";
    // Previewed: focus lands on the counts line; the primary is the next stop.
    useEffect(() => {
        if (previewed) counts.current?.focus();
    }, [previewed]);
    if (run === null || acts === null) return <Choose press={press} />;
    const list = pathFor("widget-list", {}, undefined, STAFF_SURFACE);
    if (view.repeated === true && run.applied_at !== null && run.applied_at !== undefined) {
        return (
            <div data-band="imported" className="widget-band">
                <p>{importRepeatedSentence(dayOf(run.applied_at))}</p>
            </div>
        );
    }
    switch (run.status) {
        case "checking":
            return (
                <div aria-busy="true" aria-live="polite">
                    <p>{checkingSentence(run.file_name)}</p>
                    <StillLine />
                </div>
            );
        case "imported":
            return (
                <div data-band="imported" className="widget-band">
                    <p>
                        {importedSentence(run.apply_writes, dayOf(run.applied_at ?? run.updated_at))}{" "}
                        {list === null ? null : <a href={list}>{C.title}</a>}
                    </p>
                </div>
            );
        default: {
            const importing = run.status === "importing" || press?.busy === "apply";
            const total = run.counts.create + run.counts.update + run.counts.unchanged + run.counts.refused;
            return (
                <>
                    {press?.refused === null || press?.refused === undefined ? null : (
                        <div className="widget-refusal-seat">
                            <RefusalPanel surface={STAFF_SURFACE} refusal={press.refused} seat="list-head" refused={acts.apply.words.refused} />
                        </div>
                    )}
                    {total === 0 ? (
                        <p>{nothingToImportSentence(run.file_name)}</p>
                    ) : (
                        <p ref={counts} tabIndex={-1} className="widget-counts">
                            {importCountsLine(run.counts)}
                        </p>
                    )}
                    {view.refusedRows.length === 0 ? null : (
                        <ol className="widget-history">
                            {view.refusedRows.map((row) => (
                                <li key={row.id}>{refusedRowSentence(row.row_no, detailOf(row.refusal))}</li>
                            ))}
                        </ol>
                    )}
                    {run.apply_writes === 0 || press === undefined ? null : (
                        <div className="widget-import-foot">
                            <button
                                type="button"
                                className="widget-act widget-primary"
                                {...acts.apply.attrs}
                                aria-busy={importing ? "true" : undefined}
                                onClick={press.onApply}
                            >
                                {importing ? acts.apply.busy : importApplyLabel(run.apply_writes)}
                            </button>
                        </div>
                    )}
                </>
            );
        }
    }
}

/** A refused row's sentence is the server's; the row carries the refusal body as the wire answered it. */
function detailOf(refusal: ImportRow["refusal"]): string {
    const detail = refusal?.["detail"];
    return typeof detail === "string" ? detail : "";
}
// golden: import end
