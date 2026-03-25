import { useMemo } from "react";
import Plot from "react-plotly.js";
import { EXPERIENCE_DIMS } from "../constants";
import type { ExperienceDim } from "../constants";

interface RadarSeries {
  name: string;
  values: number[];
  color?: string;
  opacity?: number;
  markerColor?: string[];
  hoverText?: string[];
}

interface RadarChartProps {
  series: RadarSeries[];
  labels?: string[];
  height?: number;
  compact?: boolean;
  margin?: { l: number; r: number; t: number; b: number };
}

const defaultLabels = EXPERIENCE_DIMS.map(
  (d) =>
    ({
      academic_intensity: "Academic",
      social_life: "Social",
      inclusivity: "Inclusivity",
      career_support: "Career",
      collaboration_vs_competition: "Collaboration",
      mental_health_culture: "Mental Health",
      campus_safety: "Safety",
      overall_satisfaction: "Satisfaction",
    })[d as ExperienceDim]
);

// Series colours: preferences (green), college (blue-grey), match zone (teal highlight)
const COLORS = [
  "rgba(106,171,122,0.55)",
  "rgba(168,184,216,0.50)",
  "rgba(72,200,168,0.35)",
];

const LINE_COLORS = [
  "rgba(106,171,122,0.9)",
  "rgba(168,184,216,0.75)",
  "rgba(72,200,168,0.85)",
];

export function RadarChart({
  series,
  labels = defaultLabels,
  height = 320,
  compact = false,
  margin,
}: RadarChartProps) {
  const labelsClosed = useMemo(() => [...labels, labels[0]], [labels]);

  // Extra bottom space for the horizontal legend
  const effectiveMargin = margin ?? (compact
    ? { l: 42, r: 42, t: 18, b: 18 }
    : { l: 52, r: 52, t: 28, b: 52 });

  const data = useMemo(
    () =>
      series.map((s, i) => {
        const valsClosed = [...s.values, s.values[0]];
        const markerClosed = s.markerColor
          ? [...s.markerColor, s.markerColor[0] ?? s.markerColor[s.markerColor.length - 1]!]
          : undefined;
        const hoverTextClosed = s.hoverText
          ? [...s.hoverText, s.hoverText[0] ?? s.hoverText[s.hoverText.length - 1]!]
          : undefined;

        const fillColor = s.color ?? COLORS[i % COLORS.length];
        const lineColor = s.color
          ? s.color.replace(/[\d.]+\)$/, "0.9)")
          : LINE_COLORS[i % LINE_COLORS.length];

        // Match zone (index 2) gets no markers and a dashed line to keep it subtle
        const isMatchZone = i === 2;

        return {
          type: "scatterpolar" as const,
          r: valsClosed,
          theta: labelsClosed,
          fill: "toself" as const,
          name: s.name,
          opacity: s.opacity ?? (isMatchZone ? 0.85 : 0.75),
          fillcolor: fillColor,
          line: {
            color: lineColor,
            width: isMatchZone ? 1.5 : compact ? 1.5 : 2,
            dash: isMatchZone ? ("dot" as const) : ("solid" as const),
          },
          // Match zone: no markers; others: small coloured dots
          mode: isMatchZone ? ("lines" as const) : ("lines+markers" as const),
          text: hoverTextClosed,
          hovertemplate: hoverTextClosed
            ? "%{theta}<br>%{text}<extra></extra>"
            : undefined,
          marker: isMatchZone
            ? { size: 0 }
            : {
                size: compact ? 4 : 6,
                color: markerClosed,
                line: { color: "rgba(255,255,255,0.3)", width: 1 },
              },
        };
      }),
    [series, labelsClosed, compact]
  );

  const layout = useMemo(
    () => ({
      polar: {
        bgcolor: "transparent",
        radialaxis: {
          visible: true,
          range: [0, 10],
          // Hide tick numbers — values are communicated through hover only
          showticklabels: false,
          ticks: "",
          gridcolor: "rgba(255,255,255,0.10)",
          gridwidth: 1,
          linecolor: "transparent",
          // Keep 5 rings for visual reference without numbers
          dtick: 2,
        },
        angularaxis: {
          tickfont: {
            size: compact ? 9 : 11,
            color: "rgba(200,210,230,0.80)",
            family: "DM Sans, system-ui, sans-serif",
          },
          gridcolor: "rgba(255,255,255,0.08)",
          linecolor: "rgba(255,255,255,0.12)",
        },
      },
      hovermode: "closest" as const,
      showlegend: !compact,
      legend: compact
        ? undefined
        : {
            font: {
              size: 11,
              color: "rgba(200,210,230,0.75)",
              family: "DM Sans, system-ui, sans-serif",
            },
            orientation: "h" as const,
            // Centred below the chart — never overlaps the polygon
            x: 0.5,
            y: -0.08,
            xanchor: "center" as const,
            yanchor: "top" as const,
            bgcolor: "transparent",
            borderwidth: 0,
            // Compact symbol so the row stays tidy
            itemsizing: "constant" as const,
          },
      margin: effectiveMargin,
      height,
      autosize: true,
      paper_bgcolor: "transparent",
      plot_bgcolor: "transparent",
    }),
    [height, effectiveMargin, compact]
  );

  return (
    <Plot
      data={data}
      layout={layout}
      useResizeHandler
      style={{ width: "100%", minHeight: height }}
      config={{ responsive: true, displayModeBar: false }}
    />
  );
}