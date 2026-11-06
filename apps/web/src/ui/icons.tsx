/** Tiny inline icons (no icon font: glyphs like ✕ are missing from many system fonts). */
const base = { width: 16, height: 16, viewBox: "0 0 16 16", fill: "none", stroke: "currentColor", strokeWidth: 2.2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true };

export const CloseIcon = () => (
  <svg {...base}><path d="M4 4l8 8M12 4l-8 8" /></svg>
);
export const CheckIcon = () => (
  <svg {...base}><path d="M3.5 8.5l3 3 6-7" /></svg>
);
export const ArrowIcon = () => (
  <svg {...base}><path d="M3 8h10M9 4l4 4-4 4" /></svg>
);

/** "Definition → word": an open dictionary. */
export const BookIcon = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d="M12 6.6C10.2 5.2 7.7 4.6 3.8 4.6v13.2c3.9 0 6.4.6 8.2 2 1.8-1.4 4.3-2 8.2-2V4.6c-3.9 0-6.4.6-8.2 2z" />
    <path d="M12 6.6v13.2M6.6 8.6h2.6M6.6 11.6h2.6M14.8 8.6h2.6M14.8 11.6h2.6" />
  </svg>
);

/** "Fill the gap": a line of text with a missing word. */
export const GapIcon = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d="M3 9.5h4.5M16.5 9.5H21M3 15.5h7M14 15.5h7" />
    <path d="M9.5 11.5h5" strokeDasharray="1.6 1.8" />
  </svg>
);
