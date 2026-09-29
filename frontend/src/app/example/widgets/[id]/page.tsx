import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { WIDGET_COPY } from "@/copy/widget";
import { REQUIRED_STORY_EXPORTS } from "@/screens/state";
import {
    ActsAfterFrame,
    ArrivedAfterMerge,
    Archived,
    AttachedMember,
    AttachLoading,
    Attached,
    Duplicated,
    Empty,
    Error as Refused,
    History,
    HistoryEmpty,
    HistoryLoading,
    Loading,
    MergeChoosing,
    Merged,
    Moved,
    NothingAttached,
    NowhereToMove,
    PopulatedAdmin,
    PopulatedMember,
    Ready,
    RefusedArchive,
    RefusedAttach,
    RefusedDuplicate,
    RefusedHistory,
    RefusedMerge,
    RefusedMove,
    RefusedRestore,
    RefusedUpdate,
    Resting,
    Stale,
} from "@/screens/widget/widget-record.stories";

/** The tab names the page's noun, not the landing it would otherwise inherit. */
export const metadata: Metadata = { title: WIDGET_COPY.title };

/**
 * The four required states, then the extras the record's entries name: §16's
 * resting record; the family's two hats; §20's archived record and its two
 * refusals; §6's acts after a frame and a refused duplicate; §17's moved-away,
 * copied and merged bands; §10's History card read, being read, empty and
 * refused; and the attach cards and tag row on both hats, being read, empty
 * and an add refused.
 */
const WALK = [
    ...REQUIRED_STORY_EXPORTS.map((name) => ({ name, Story: { Loading, Empty, Error: Refused, Ready }[name] })),
    { name: "Resting", Story: Resting },
    { name: "PopulatedAdmin", Story: PopulatedAdmin },
    { name: "PopulatedMember", Story: PopulatedMember },
    { name: "Archived", Story: Archived },
    { name: "RefusedArchive", Story: RefusedArchive },
    { name: "RefusedRestore", Story: RefusedRestore },
    { name: "ActsAfterFrame", Story: ActsAfterFrame },
    { name: "Moved", Story: Moved },
    { name: "Duplicated", Story: Duplicated },
    { name: "RefusedDuplicate", Story: RefusedDuplicate },
    { name: "Merged", Story: Merged },
    { name: "History", Story: History },
    { name: "HistoryLoading", Story: HistoryLoading },
    { name: "HistoryEmpty", Story: HistoryEmpty },
    { name: "RefusedHistory", Story: RefusedHistory },
    { name: "Attached", Story: Attached },
    { name: "AttachedMember", Story: AttachedMember },
    { name: "AttachLoading", Story: AttachLoading },
    { name: "NothingAttached", Story: NothingAttached },
    { name: "RefusedAttach", Story: RefusedAttach },
] as const;

/**
 * §1's stories (the merge chooser and its confirm among them) open a sheet — a MODAL dialog — as they render, and two modals
 * on one page make everything but the last one inert. So they are walked one
 * at a time, `?story=<name>`, each alone on the page; the default walk draws
 * every other story, and a sheet there opens from the admin story's *Edit* and
 * *Move*.
 */
const ALONE = {
    Stale,
    RefusedUpdate,
    RefusedMove,
    NowhereToMove,
    MergeChoosing,
    RefusedMerge,
    // Lands focus on its name as it renders: walked alone, like the sheets.
    ArrivedAfterMerge,
} as const;

type SearchParams = Readonly<Record<string, string | readonly string[] | undefined>>;

/**
 * EXAMPLE — THE WORKED WIDGET RECORD, WALKED. Development only, `/states`'
 * pattern: in a production build this route is a 404.
 *
 * It renders the record screen's stories whatever the id, because the walk is
 * of the screen's states, not of one row: the list walk's rows land here, and
 * so does any id typed by hand. `data-story` labels each section for the
 * rendered drive; `Ready` is the populated case.
 */
export default async function WidgetRecordExamplePage({ searchParams }: { readonly searchParams?: Promise<SearchParams> }) {
    if (process.env.NODE_ENV === "production") {
        notFound();
    }
    const asked = (await searchParams)?.story;
    const alone = typeof asked === "string" && asked in ALONE ? asked : null;
    const walk = alone === null ? WALK : [{ name: alone, Story: ALONE[alone as keyof typeof ALONE] }];

    return (
        <div data-example="widget-record">
            {walk.map(({ name, Story }) => (
                <section key={name} data-story={name}>
                    <Story />
                </section>
            ))}
        </div>
    );
}
