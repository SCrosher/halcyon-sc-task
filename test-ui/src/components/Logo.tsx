/**
 * Halcyon emblem: a sun resting on a still horizon, with its reflection on calm water.
 * Fine bronze linework on an ink tile, echoing an engraved seal.
 */
export function Emblem({ size = 32, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" className={className} aria-hidden>
      <rect width="32" height="32" rx="9" fill="#17171B" />
      <rect x="0.5" y="0.5" width="31" height="31" rx="8.5" fill="none" stroke="#C9B27C" strokeOpacity="0.18" />
      <g fill="none" stroke="#C9B27C" strokeLinecap="round" strokeWidth="1.15">
        <path d="M10.25 17.25a5.75 5.75 0 0 1 11.5 0" />
        <path d="M7.5 17.25h17" />
        <path d="M10.5 20.5h11" strokeOpacity="0.7" />
        <path d="M13 23.5h6" strokeOpacity="0.45" />
      </g>
      <circle cx="16" cy="8.4" r="0.85" fill="#C9B27C" fillOpacity="0.85" />
    </svg>
  );
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={className}>
      <span className="font-display text-[19px] leading-none font-medium tracking-[0.32em] text-ink uppercase">
        Halcyon
      </span>
    </span>
  );
}
