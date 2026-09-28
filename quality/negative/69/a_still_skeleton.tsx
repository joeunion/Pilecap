const NOTE = "No spinner here, and no toast: still shapes only.";

export function RowsSkeleton() {
    return (
        <div aria-busy="true" title={NOTE}>
            <div className="row-skeleton" />
        </div>
    );
}
