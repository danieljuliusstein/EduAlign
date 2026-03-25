import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { EXPERIENCE_DIMS, DIMENSION_LABELS } from "../constants";
import { RadarChart } from "./RadarChart";
import { saveCollege, getReviewSummary } from "../api";
import type { MatchItem, Preferences } from "../types";
import { Heart, Star } from "lucide-react";

interface Props {
  match: MatchItem;
  studentPrefs: Preferences;
  rank: number;
}

const SHORT_LABELS: Record<string, string> = {
  "Academic Intensity": "Academic",
  "Social Life": "Social Life",
  "Inclusivity": "Inclusivity",
  "Career Support": "Career",
  "Collaboration vs Competition": "Collaboration",
  "Mental Health Culture": "Mental Health",
  "Campus Safety": "Safety",
  "Overall Satisfaction": "Satisfaction",
};

export function CollegeCard({ match, studentPrefs, rank }: Props) {
  const navigate = useNavigate();
  const [expanded, setExpanded] = useState(false);
  const [saved, setSaved] = useState(false);
  const [reviewCount, setReviewCount] = useState<number>(0);
  const [avgRating, setAvgRating] = useState<number | null>(null);

  useEffect(() => {
    if (match.UNITID) {
      getReviewSummary(match.UNITID)
        .then((s) => { setReviewCount(s.review_count); setAvgRating(s.avg_rating); })
        .catch(() => {});
    }
  }, [match.UNITID]);

  const handleSave = async () => {
    if (!match.UNITID || saved) return;
    try {
      await saveCollege(match.UNITID, "target");
      setSaved(true);
    } catch { /* ignore */ }
  };

  const labels = EXPERIENCE_DIMS.map(
    (d) => SHORT_LABELS[DIMENSION_LABELS[d]] ?? DIMENSION_LABELS[d]
  );
  // Keep both polygons on the same normalized 0-10 scale.
  // - Student sliders are already 1-10 (importance / preference intensity).
  // - Backend match dimensions are typically 0-1; scale to 0-10 for direct comparison.
  const neutralVal = 5;
  const clamp01to10 = (v: number) => Math.max(0, Math.min(10, v));
  const normalizeCollegeDim = (raw: unknown) => {
    const n = typeof raw === "number" ? raw : Number(raw);
    if (!Number.isFinite(n)) return 0;
    if (n <= 1.01) return clamp01to10(n * 10);
    if (n <= 10.01) return clamp01to10(n);
    return clamp01to10(n);
  };

  const studentVals = EXPERIENCE_DIMS.map((d) => {
    const v = typeof studentPrefs?.[d] === "number" ? studentPrefs[d] : Number((studentPrefs as Record<string, unknown>)[d]);
    // Sliders are 1-10; treat 0/invalid as "not rated" -> neutral.
    if (!Number.isFinite(v) || v <= 0) return neutralVal;
    return clamp01to10(v);
  });

  const collegeVals = EXPERIENCE_DIMS.map((d) => normalizeCollegeDim((match as Record<string, unknown>)[d]));

  const hasProfile = collegeVals.some((v) => v > 0);
  const scorePct = ((match.similarity_score ?? 0) * 100).toFixed(0);

  const strengths = new Set(match.strengths ?? []);
  const tradeoffs = new Set(match.tradeoffs ?? []);
  const axisMarkerColors = EXPERIENCE_DIMS.map((d) => {
    // Mirror the existing strength/tradeoff semantics from the colored pills:
    // - Green for strengths (match)
    // - Orange for tradeoffs (concern)
    if (tradeoffs.has(d)) return "rgba(251,191,36,1)"; // amber/orange
    if (strengths.has(d)) return "rgba(141,217,160,1)"; // matching green
    return "rgba(168,184,216,0.95)"; // neutral
  });

  const hoverTexts = labels.map((_, i) => {
    const studentV = studentVals[i] ?? neutralVal;
    const collegeV = collegeVals[i] ?? 0;
    return `Your Preferences: ${studentV.toFixed(1)}<br>College Ratings: ${collegeV.toFixed(1)}`;
  });

  return (
    <div className="mc">
      <div className="mc-bg">
        {/* Header */}
        <div className="mc-header">
          <div>
            <div className="mc-rank">Match #{rank}</div>
            <div className="mc-name">{match.INSTNM}</div>
            {reviewCount > 0 && (
              <div
                style={{ fontSize: "0.75rem", color: "#f59e0b", cursor: "pointer", marginTop: "0.1rem" }}
                onClick={(e) => { e.stopPropagation(); navigate(`/reviews/${match.UNITID}`); }}
              >
                {[1, 2, 3, 4, 5].map((n) => (
                  <Star key={n} size={11} fill={n <= Math.round(avgRating ?? 0) ? "currentColor" : "none"} style={{ verticalAlign: -1 }} />
                ))}
                {" "}{avgRating?.toFixed(1)} ({reviewCount})
              </div>
            )}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <button
              type="button"
              onClick={handleSave}
              title={saved ? "Saved!" : "Save to My Colleges"}
              style={{
                background: "none", border: "none", cursor: saved ? "default" : "pointer",
                lineHeight: 1, padding: 0,
                color: saved ? "#e74c3c" : "rgba(255,255,255,0.4)",
                transition: "color 0.2s",
              }}
            >
              <Heart size={20} fill={saved ? "currentColor" : "none"} />
            </button>
            <div className="mc-score">
              <span className="mc-score-num">{scorePct}</span>
              <span className="mc-score-pct">match</span>
            </div>
          </div>
        </div>

        {/* Explanation */}
        <div className={`mc-explanation${expanded ? " expanded" : ""}`}>
          {match.explanation}
        </div>
        {match.explanation && match.explanation.length > 140 && (
          <button
            type="button"
            className="mc-read-more"
            onClick={() => setExpanded((e) => !e)}
          >
            {expanded ? "Show less" : "Read more"}
          </button>
        )}

        {/* Strength / Tradeoff pills */}
        <div className="mc-tags">
          {match.strengths?.slice(0, 3).map((s) => (
            <span key={s} className="mc-pill mc-pill-strength">
              {DIMENSION_LABELS[s as keyof typeof DIMENSION_LABELS] ?? s}
            </span>
          ))}
          {match.tradeoffs?.slice(0, 2).map((t) => (
            <span key={t} className="mc-pill mc-pill-tradeoff">
              {DIMENSION_LABELS[t as keyof typeof DIMENSION_LABELS] ?? t}
            </span>
          ))}
        </div>

        {/* Radar */}
        {hasProfile && (
          <div className="mc-radar-wrap">
            <RadarChart
              height={280}
              labels={labels}
              series={[
                {
                  name: "Your Preferences",
                  values: studentVals,
                  color: "rgba(106,171,122,0.6)",
                  opacity: 1,
                  markerColor: axisMarkerColors,
                  hoverText: hoverTexts,
                },
                {
                  name: "College Ratings",
                  values: collegeVals,
                  color: "rgba(168,184,216,0.6)",
                  opacity: 1,
                  markerColor: axisMarkerColors,
                  hoverText: hoverTexts,
                },
              ]}
            />
          </div>
        )}

        {/* Footer */}
        {match.UNITID && (
          <>
            <div className="mc-divider" />
            <div className="mc-footer">
              <a
                className="mc-explore"
                href="#"
                onClick={(e) => {
                  e.preventDefault();
                  navigate(`/financial?unitid=${match.UNITID}`);
                }}
              >
                Financial Plan
                <svg viewBox="0 0 20 20" fill="currentColor" width="16" height="16">
                  <path
                    fillRule="evenodd"
                    d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z"
                    clipRule="evenodd"
                  />
                </svg>
              </a>
              <a
                className="mc-explore"
                href="#"
                onClick={(e) => {
                  e.preventDefault();
                  navigate("/compare");
                }}
              >
                Compare
                <svg viewBox="0 0 20 20" fill="currentColor" width="16" height="16">
                  <path
                    fillRule="evenodd"
                    d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z"
                    clipRule="evenodd"
                  />
                </svg>
              </a>
              <a
                className="mc-explore"
                href="#"
                onClick={(e) => {
                  e.preventDefault();
                  navigate(`/reviews/${match.UNITID}`);
                }}
              >
                Reviews
                <svg viewBox="0 0 20 20" fill="currentColor" width="16" height="16">
                  <path
                    fillRule="evenodd"
                    d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z"
                    clipRule="evenodd"
                  />
                </svg>
              </a>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
