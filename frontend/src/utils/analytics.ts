import { postAnalyticsEvent, type PortfolioAnalyticsEventType } from "../api";

const ATTR_KEY = "edualign_portfolio_attr_v1";
const SESSION_KEY = "edualign_analytics_session_v1";
const LANDING_KEY = "edualign_landing_sent_v1";

const UTM_KEYS = [
  "utm_source",
  "utm_medium",
  "utm_campaign",
  "utm_content",
  "utm_term",
] as const;

/** Merge UTM params from the current URL into first-touch attribution (localStorage). */
export function absorbUtmsFromCurrentUrl(): void {
  if (typeof window === "undefined") return;
  const params = new URLSearchParams(window.location.search);
  const patch: Partial<Record<(typeof UTM_KEYS)[number], string>> = {};
  let touched = false;
  for (const k of UTM_KEYS) {
    const v = params.get(k);
    if (v?.trim()) {
      patch[k] = v.trim().slice(0, 256);
      touched = true;
    }
  }
  if (!touched) return;
  try {
    const prev = JSON.parse(localStorage.getItem(ATTR_KEY) || "{}") as Record<string, string>;
    const next = { ...prev };
    for (const [k, v] of Object.entries(patch)) {
      if (v && !next[k]) next[k] = v;
    }
    localStorage.setItem(ATTR_KEY, JSON.stringify(next));
  } catch {
    localStorage.setItem(ATTR_KEY, JSON.stringify(patch));
  }
}

export function getAttribution(): Record<string, string | undefined> {
  try {
    return JSON.parse(localStorage.getItem(ATTR_KEY) || "{}") as Record<string, string | undefined>;
  } catch {
    return {};
  }
}

export function getOrCreateSessionId(): string {
  if (typeof sessionStorage === "undefined") {
    return `fallback-${Date.now()}`;
  }
  let id = sessionStorage.getItem(SESSION_KEY);
  if (!id) {
    id =
      typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
    sessionStorage.setItem(SESSION_KEY, id);
  }
  return id;
}

export function trackEvent(
  eventType: PortfolioAnalyticsEventType,
  metadata?: Record<string, unknown>,
  pathOverride?: string
): void {
  if (typeof window === "undefined") return;
  absorbUtmsFromCurrentUrl();
  const attr = getAttribution();
  const sessionId = getOrCreateSessionId();
  const ref =
    typeof document !== "undefined" && document.referrer
      ? document.referrer.slice(0, 2048)
      : null;
  const path =
    pathOverride ?? (typeof window !== "undefined" ? window.location.pathname.slice(0, 512) : "/");

  void postAnalyticsEvent({
    session_id: sessionId,
    event_type: eventType,
    utm_source: attr.utm_source ?? null,
    utm_medium: attr.utm_medium ?? null,
    utm_campaign: attr.utm_campaign ?? null,
    utm_content: attr.utm_content ?? null,
    utm_term: attr.utm_term ?? null,
    referrer: ref,
    path,
    metadata: metadata ?? null,
  });
}

/** One `landing` per browser tab session (sessionStorage). */
export function trackLandingOnce(): void {
  if (typeof sessionStorage === "undefined") return;
  if (sessionStorage.getItem(LANDING_KEY)) return;
  sessionStorage.setItem(LANDING_KEY, "1");
  trackEvent("landing");
}

export function trackPageView(pathname: string): void {
  trackEvent("page_view", undefined, pathname);
}
