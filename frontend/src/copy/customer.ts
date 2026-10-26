/**
 * EXAMPLE — the worked customer face's words (patterns.md §21): the second
 * surface a product copies beside the staff face (`screens/customer/`). Every
 * label is a lexicon row, every sentence plain, and no machine token reaches a
 * reader.
 */

// golden: portal begin
export const CUSTOMER_COPY = {
    /** The widget list's title and the record's crumb: the staff noun, read-only here. */
    widgetsTitle: "Widgets",
    /** The requests page's title and a request's crumb. */
    requestsTitle: "Requests",

    /** The card that sends one (§10): its title, its two fields, its one act and its forms. */
    sendTitle: "Send a request",
    widgetLabel: "Widget",
    noteLabel: "Your question",
    sendAct: "Send",
    sendingAct: "Sending…",
    sentLabel: "Sent",
    sendRefusedLabel: "Couldn't send",

    /** A request's facts. */
    askedByLabel: "Asked by",
    addedLabel: "Added",

    /** The widget record's door to the card, carrying the widget. */
    askAboutAct: "Send a request",

    /** What an empty list says, and the act it proposes (§14). */
    noWidgets: "No widgets are shared with you yet.",
    noWidgetsDetail: "When the team shares a widget with your organization, it appears here.",
    noRequests: "You have not sent a request yet.",
    noRequestsDetail: "Choose a widget above and ask what you need; the answer comes back to you here.",
    notFoundRecord: "Nothing to show here.",

    /** A field left empty, said before anything is sent. */
    chooseWidget: "Choose the widget your question is about.",
    writeNote: "Write what you want to ask.",

    loading: "Reading…",
} as const;
// golden: portal end
