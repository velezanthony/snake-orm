/** The one "we are waiting" the app shows, so waiting looks the same everywhere. */
export function PageSpinner({ label = "Loading…" }: { label?: string }) {
  return (
    <p className="lede" role="status" aria-live="polite">
      {label}
    </p>
  );
}
