interface EduAlignLogoProps {
  /** Approximate height of the logo in pixels. */
  height?: number;
  className?: string;
  /** Use for dark backgrounds (e.g. sidebar) so the black SVG becomes light. */
  dark?: boolean;
}

/**
 * Uses the provided `frontend/public/EduAlign.svg` so all pages stay consistent.
 */
export function EduAlignLogo({ height = 48, className = "", dark = false }: EduAlignLogoProps) {
  return (
    <img
      className={className}
      src="/EduAlign.svg"
      alt="EduAlign"
      style={{
        height,
        width: "auto",
        display: "block",
        // The source SVG uses `fill="#000000"`, so invert it for dark UI.
        filter: dark ? "invert(1) brightness(2)" : "none",
      }}
    />
  );
}
