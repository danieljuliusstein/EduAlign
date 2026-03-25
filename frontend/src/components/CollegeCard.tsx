// ─── Radar data ────────────────────────────────────────────────────────────
  // All three polygons share the same 0–10 scale so they're directly comparable.

  const studentVals = EXPERIENCE_DIMS.map((d) => {
    const v =
      typeof studentPrefs?.[d] === "number"
        ? studentPrefs[d]
        : Number((studentPrefs as Record<string, unknown>)[d]);
    if (!Number.isFinite(v) || v <= 0) return neutralVal;
    return clamp01to10(v);
  });

  const collegeVals = EXPERIENCE_DIMS.map((d) =>
    normalizeCollegeDim((match as Record<string, unknown>)[d])
  );

  // Match zone: per-axis minimum of the two polygons — the "overlap" area.
  const matchZoneVals = studentVals.map((sv, i) =>
    Math.min(sv, collegeVals[i] ?? 0)
  );

  const hasProfile = collegeVals.some((v) => v > 0);

  // ─── Axis marker colours (strength = green, tradeoff = amber) ──────────────
  const strengths = new Set(match.strengths ?? []);
  const tradeoffs = new Set(match.tradeoffs ?? []);
  const axisMarkerColors = EXPERIENCE_DIMS.map((d) => {
    if (tradeoffs.has(d)) return "rgba(251,191,36,1)";
    if (strengths.has(d)) return "rgba(141,217,160,1)";
    return "rgba(168,184,216,0.95)";
  });

  const hoverTexts = labels.map((_, i) => {
    const studentV = studentVals[i] ?? neutralVal;
    const collegeV = collegeVals[i] ?? 0;
    return `Your Preferences: ${studentV.toFixed(1)}<br>College Ratings: ${collegeV.toFixed(1)}`;
  });

  // ─── Radar JSX ─────────────────────────────────────────────────────────────
  // Three series, back-to-front render order:
  //   1. College Ratings (bottom)
  //   2. Your Preferences (middle)
  //   3. Match Zone / overlap (top, subtle teal fill)
  const radarSeries = [
    {
      name: "College Ratings",
      values: collegeVals,
      color: "rgba(168,184,216,0.50)",
      opacity: 1,
      markerColor: axisMarkerColors,
      hoverText: hoverTexts,
    },
    {
      name: "Your Preferences",
      values: studentVals,
      color: "rgba(106,171,122,0.55)",
      opacity: 1,
      markerColor: axisMarkerColors,
      hoverText: hoverTexts,
    },
    {
      name: "Match Zone",
      values: matchZoneVals,
      color: "rgba(72,200,168,0.28)",
      opacity: 1,
      // Match zone has no per-axis markers; hoverText still shows divergence
      hoverText: hoverTexts,
    },
  ];

  // ─── Render (replace the existing {hasProfile && ...} block) ───────────────
  return hasProfile ? (
    <div className="mc-radar-wrap">
      <RadarChart
        height={300}
        labels={labels}
        series={radarSeries}
      />
    </div>
  ) : null;