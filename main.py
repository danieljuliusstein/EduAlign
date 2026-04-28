"""
FastAPI backend for EduAlign.
"""

import json
import math
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Any

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session


def _clean(records: list[dict]) -> list[dict]:
    """Replace NaN/Inf with None so JSON serialization succeeds."""
    for rec in records:
        for k, v in rec.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                rec[k] = None
    return records

def _cors_allow_origins() -> list[str]:
    """
    CORS allow-list for browser origins.

    Configure in production via `CORS_ORIGINS` (comma-separated).
    Falls back to local dev origins when unset.
    """
    raw = os.getenv("CORS_ORIGINS", "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

from backend.activity import log_activity
from backend.auth import router as auth_router
from backend.auth.routes import get_current_user, get_current_user_optional
from backend.colleges import EXPERIENCE_DIMS, get_matches, get_predictions, suggest_sliders, load_merged_data
from backend.database import get_db, init_db, run_migrations
from backend.models import (
    User,
    UserActivity,
    UserProfile,
    SavedCollege,
    SavedPlan,
    SavedComparison,
    Review,
    ReviewVote,
    REVIEW_TAGS,
    PortfolioAnalyticsEvent,
)
from backend.financials import (
    budget_tracker,
    estimate_semester_cost,
    find_alternatives,
    graduation_plan,
)

app = FastAPI(title="EduAlign API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health endpoint for Render health checks / keep-alive pings.
@app.get("/health")
def health():
    return {"ok": True}

# Auth: signup, login, Google login
app.include_router(auth_router)


@app.on_event("startup")
def startup():
    # Keep startup fast/reliable for hosted environments.
    # `build.sh` already runs `init_db()` and `run_migrations()` during deployment,
    # so re-running migrations on every process start can delay port binding.
    print("[startup] init_db()")
    init_db()

    if os.getenv("EDUALIGN_RUN_MIGRATIONS_ON_STARTUP", "0") == "1":
        print("[startup] run_migrations()")
        run_migrations()
    else:
        print("[startup] skip run_migrations() (set EDUALIGN_RUN_MIGRATIONS_ON_STARTUP=1 to enable)")

_colleges_df = None


def _get_colleges():
    global _colleges_df
    if _colleges_df is None:
        _colleges_df = load_merged_data()
    return _colleges_df


# ── Request / Response Models ────────────────────────────────────────────────


class StudentProfile(BaseModel):
    gpa: Optional[float] = None
    sat: Optional[int] = None
    major: Optional[str] = None
    location: Optional[str] = None
    extracurriculars: Optional[str] = None
    in_state_preference: Optional[bool] = None
    free_text: Optional[str] = None


class MatchRequest(BaseModel):
    preferences: dict
    top_n: int = 4
    profile: Optional[StudentProfile] = None


class FinancialPlanRequest(BaseModel):
    unitid: int
    budget_per_semester: float
    total_savings: float
    in_state: bool = True
    on_campus: bool = True
    degree_years: int = 4


class AlternativesRequest(BaseModel):
    budget_per_semester: float
    state: Optional[str] = None
    in_state: bool = True
    limit: int = 10


class BudgetTrackerRequest(BaseModel):
    total_cost: float
    semesters_completed: int
    total_semesters: int
    amount_spent: float


class CompareRequest(BaseModel):
    unitids: list[int]
    in_state: bool = True
    on_campus: bool = True


class PredictRequest(BaseModel):
    profile: StudentProfile
    unitids: list[int]


class SuggestSlidersRequest(BaseModel):
    profile: StudentProfile


class SaveProfileRequest(BaseModel):
    gpa: Optional[float] = None
    sat: Optional[int] = None
    major: Optional[str] = None
    location: Optional[str] = None
    extracurriculars: Optional[str] = None
    in_state_preference: Optional[bool] = False
    free_text: Optional[str] = None
    sliders: Optional[dict] = None


class SliderSaveRequest(BaseModel):
    # Experience sliders, keyed by UserProfile.SLIDER_KEYS (each 1-10).
    sliders: dict[str, float]


# ── Endpoints ────────────────────────────────────────────────────────────────


@app.post("/api/match")
def api_match(
    req: MatchRequest,
    user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    for dim in EXPERIENCE_DIMS:
        if dim not in req.preferences:
            raise HTTPException(400, f"Missing dimension: {dim}")
    profile_dict = req.profile.model_dump(exclude_none=True) if req.profile else None
    result = get_matches(req.preferences, req.top_n, profile=profile_dict)
    matches = []
    used_fallback = result.get("used_fallback", False)
    for m in result["matches"]:
        m["INSTNM"] = m.pop("college_name", m.get("INSTNM", "Unknown"))
        for k, v in m.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                m[k] = None
        matches.append(m)
    top = matches[0] if matches else {}
    log_activity(db, user.id if user else None, "match_search", {
        "top_college": top.get("INSTNM"),
        "similarity_score": top.get("similarity_score"),
        "used_llm": not used_fallback,
    })
    return {"matches": matches, "used_fallback": used_fallback}


@app.get("/api/colleges")
def api_colleges(search: str = "", state: str = "", limit: int = 50):
    df = _get_colleges()
    if search:
        df = df[df["INSTNM"].str.contains(search, case=False, na=False)]
    if state:
        df = df[df["STABBR"] == state.upper()]
    subset = df.head(limit)[
        ["UNITID", "INSTNM", "CITY", "STABBR", "CONTROL", "UGDS", "TUITIONFEE_IN", "TUITIONFEE_OUT"]
    ]
    return _clean(subset.to_dict(orient="records"))


@app.get("/api/colleges/{unitid}")
def api_college_detail(unitid: int):
    df = _get_colleges()
    row = df[df["UNITID"] == unitid]
    if row.empty:
        raise HTTPException(404, "College not found")
    record = row.iloc[0].to_dict()
    for k, v in record.items():
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            record[k] = None
    return record


@app.post("/api/financial-plan")
def api_financial_plan(
    req: FinancialPlanRequest,
    user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    result = graduation_plan(
        unitid=req.unitid,
        budget_per_semester=req.budget_per_semester,
        total_savings=req.total_savings,
        in_state=req.in_state,
        on_campus=req.on_campus,
        degree_years=req.degree_years,
    )
    if "error" in result:
        raise HTTPException(400, result["error"])
    log_activity(db, user.id if user else None, "financial_plan", {
        "unitid": req.unitid,
        "college_name": result.get("college_name"),
        "can_graduate_on_time": result.get("can_graduate_on_time"),
    })
    return result


@app.post("/api/alternatives")
def api_alternatives(req: AlternativesRequest):
    df = find_alternatives(
        budget_per_semester=req.budget_per_semester,
        state=req.state,
        in_state=req.in_state,
        limit=req.limit,
    )
    return _clean(df.to_dict(orient="records"))


@app.post("/api/budget-tracker")
def api_budget_tracker(req: BudgetTrackerRequest):
    return budget_tracker(
        total_cost=req.total_cost,
        semesters_completed=req.semesters_completed,
        total_semesters=req.total_semesters,
        amount_spent=req.amount_spent,
    )


@app.post("/api/compare")
def api_compare(req: CompareRequest):
    results = []
    for uid in req.unitids:
        cost = estimate_semester_cost(uid, req.in_state, req.on_campus)
        if "error" not in cost:
            results.append(cost)
    return results


@app.post("/api/predict")
def api_predict(req: PredictRequest):
    profile_dict = req.profile.model_dump(exclude_none=True)
    if not req.unitids:
        raise HTTPException(400, "At least one UNITID is required")
    result = get_predictions(profile_dict, req.unitids)
    return result


@app.post("/api/suggest-sliders")
def api_suggest_sliders(req: SuggestSlidersRequest):
    profile_dict = req.profile.model_dump(exclude_none=True)
    return {"suggested_sliders": suggest_sliders(profile_dict)}


@app.get("/api/profile")
def api_get_profile(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.query(UserProfile).filter(UserProfile.user_id == user.id).first()
    if not row:
        return {"saved": False}
    return {"saved": True, **row.to_dict()}


@app.put("/api/profile")
def api_save_profile(req: SaveProfileRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.query(UserProfile).filter(UserProfile.user_id == user.id).first()
    if not row:
        row = UserProfile(user_id=user.id)
        db.add(row)

    row.gpa = req.gpa
    row.sat = req.sat
    row.major = req.major
    row.location = req.location
    row.extracurriculars = req.extracurriculars
    row.in_state_preference = req.in_state_preference or False
    row.free_text = req.free_text

    if req.sliders:
        for key in UserProfile.SLIDER_KEYS:
            if key in req.sliders:
                setattr(row, key, req.sliders[key])

    db.commit()
    db.refresh(row)
    return {"saved": True, **row.to_dict()}


@app.get("/api/profile/sliders")
def api_get_profile_sliders(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.query(UserProfile).filter(UserProfile.user_id == user.id).first()
    if not row:
        return {"saved": False}
    return {"saved": True, "sliders": row.to_dict().get("sliders", {})}


@app.put("/api/profile/sliders")
def api_save_profile_sliders(
    req: SliderSaveRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(UserProfile).filter(UserProfile.user_id == user.id).first()
    if not row:
        row = UserProfile(user_id=user.id)
        db.add(row)

    # Clamp slider values to 1-10.
    for key in UserProfile.SLIDER_KEYS:
        if key not in req.sliders:
            continue
        try:
            val = float(req.sliders[key])
        except (TypeError, ValueError):
            continue
        val = max(1.0, min(10.0, val))
        # UserProfile slider columns are Integer; store whole numbers.
        setattr(row, key, int(round(val)))

    db.commit()
    db.refresh(row)
    return {"saved": True, "sliders": row.to_dict().get("sliders", {})}


# ── Saved Colleges ───────────────────────────────────────────────────────────


class SaveCollegeRequest(BaseModel):
    unitid: int
    tier: str = "target"
    notes: Optional[str] = None


class UpdateSavedCollegeRequest(BaseModel):
    tier: Optional[str] = None
    notes: Optional[str] = None


@app.get("/api/saved-colleges")
def api_get_saved_colleges(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(SavedCollege).filter(SavedCollege.user_id == user.id).order_by(SavedCollege.saved_at.desc()).all()
    df = _get_colleges()
    results = []
    for sc in rows:
        d = sc.to_dict()
        col = df[df["UNITID"] == sc.unitid]
        if not col.empty:
            r = col.iloc[0]
            d["college_name"] = r.get("INSTNM", "Unknown")
            # Guard against pandas NaN so frontend doesn't render blank/invalid text.
            city = r.get("CITY")
            stabbr = r.get("STABBR")
            d["city"] = None if pd.isna(city) else str(city)
            d["state"] = None if pd.isna(stabbr) else str(stabbr)
            d["adm_rate"] = None if pd.isna(r.get("ADM_RATE")) else float(r["ADM_RATE"])
            d["grad_rate"] = None if pd.isna(r.get("C150_4")) else float(r["C150_4"])
            d["median_earnings"] = None if pd.isna(r.get("MD_EARN_WNE_P10")) else float(r["MD_EARN_WNE_P10"])
        results.append(d)
    return results


@app.post("/api/saved-colleges")
def api_save_college(
    req: SaveCollegeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = db.query(SavedCollege).filter(
        SavedCollege.user_id == user.id, SavedCollege.unitid == req.unitid
    ).first()
    if existing:
        existing.tier = req.tier
        if req.notes is not None:
            existing.notes = req.notes
        db.commit()
        db.refresh(existing)
        return existing.to_dict()
    sc = SavedCollege(user_id=user.id, unitid=req.unitid, tier=req.tier, notes=req.notes)
    db.add(sc)
    db.commit()
    db.refresh(sc)
    log_activity(db, user.id, "save_college", {"unitid": req.unitid, "tier": req.tier})
    return sc.to_dict()


@app.patch("/api/saved-colleges/{unitid}")
def api_update_saved_college(
    unitid: int,
    req: UpdateSavedCollegeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sc = db.query(SavedCollege).filter(
        SavedCollege.user_id == user.id, SavedCollege.unitid == unitid
    ).first()
    if not sc:
        raise HTTPException(404, "Saved college not found")
    if req.tier is not None:
        sc.tier = req.tier
    if req.notes is not None:
        sc.notes = req.notes
    db.commit()
    db.refresh(sc)
    return sc.to_dict()


@app.delete("/api/saved-colleges/{unitid}")
def api_delete_saved_college(
    unitid: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sc = db.query(SavedCollege).filter(
        SavedCollege.user_id == user.id, SavedCollege.unitid == unitid
    ).first()
    if not sc:
        raise HTTPException(404, "Saved college not found")
    db.delete(sc)
    db.commit()
    return {"deleted": True, "unitid": unitid}


# ── Saved Plans ──────────────────────────────────────────────────────────────


class SavePlanRequest(BaseModel):
    unitid: int
    college_name: Optional[str] = None
    inputs: dict
    result: dict


@app.get("/api/saved-plans")
def api_get_saved_plans(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(SavedPlan).filter(SavedPlan.user_id == user.id).order_by(SavedPlan.created_at.desc()).all()
    return [r.to_dict() for r in rows]


@app.post("/api/saved-plans")
def api_save_plan(
    req: SavePlanRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sp = SavedPlan(
        user_id=user.id,
        unitid=req.unitid,
        college_name=req.college_name,
        inputs=req.inputs,
        result=req.result,
    )
    db.add(sp)
    db.commit()
    db.refresh(sp)
    return sp.to_dict()


@app.delete("/api/saved-plans/{plan_id}")
def api_delete_saved_plan(
    plan_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sp = db.query(SavedPlan).filter(SavedPlan.id == plan_id, SavedPlan.user_id == user.id).first()
    if not sp:
        raise HTTPException(404, "Saved plan not found")
    db.delete(sp)
    db.commit()
    return {"deleted": True, "id": plan_id}


# ── Saved Comparisons ───────────────────────────────────────────────────────


class SaveComparisonRequest(BaseModel):
    unitids: list[int]
    label: Optional[str] = None


@app.get("/api/saved-comparisons")
def api_get_saved_comparisons(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(SavedComparison).filter(SavedComparison.user_id == user.id).order_by(SavedComparison.created_at.desc()).all()
    df = _get_colleges()
    results = []
    for sc in rows:
        d = sc.to_dict()
        names = []
        for uid in (sc.unitids or []):
            col = df[df["UNITID"] == uid]
            names.append(col.iloc[0]["INSTNM"] if not col.empty else str(uid))
        d["college_names"] = names
        results.append(d)
    return results


@app.post("/api/saved-comparisons")
def api_save_comparison(
    req: SaveComparisonRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sc = SavedComparison(user_id=user.id, unitids=req.unitids, label=req.label)
    db.add(sc)
    db.commit()
    db.refresh(sc)
    return sc.to_dict()


@app.delete("/api/saved-comparisons/{comp_id}")
def api_delete_saved_comparison(
    comp_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sc = db.query(SavedComparison).filter(SavedComparison.id == comp_id, SavedComparison.user_id == user.id).first()
    if not sc:
        raise HTTPException(404, "Saved comparison not found")
    db.delete(sc)
    db.commit()
    return {"deleted": True, "id": comp_id}


# ── Match History ────────────────────────────────────────────────────────────


@app.get("/api/my/match-history")
def api_match_history(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (
        db.query(UserActivity)
        .filter(UserActivity.user_id == user.id, UserActivity.action_type == "match_search")
        .order_by(UserActivity.created_at.desc())
        .limit(10)
        .all()
    )
    return [
        {
            "id": r.id,
            "metadata": r.metadata_,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


# ── Reviews ──────────────────────────────────────────────────────────────────


class CreateReviewRequest(BaseModel):
    unitid: int
    overall_rating: int
    dimension_ratings: dict
    pros: str
    cons: str
    advice: Optional[str] = None
    would_recommend: str
    attendance_status: str
    year: Optional[str] = None
    major: Optional[str] = None
    tags: list[str] = []


@app.get("/api/reviews/tags")
def api_review_tags():
    return REVIEW_TAGS


@app.get("/api/reviews/college/{unitid}")
def api_college_reviews(unitid: int, db: Session = Depends(get_db)):
    from sqlalchemy import func as sa_func

    rows = (
        db.query(Review, User.username)
        .outerjoin(User, Review.user_id == User.id)
        .filter(Review.unitid == unitid)
        .order_by(Review.created_at.desc())
        .all()
    )
    reviews = [r.to_dict(username=uname) for r, uname in rows]

    if not reviews:
        return {"reviews": [], "aggregate": None}

    avg_overall = sum(r["overall_rating"] for r in reviews) / len(reviews)

    dim_totals: dict[str, list[float]] = {}
    for r in reviews:
        if r["dimension_ratings"]:
            for k, v in r["dimension_ratings"].items():
                dim_totals.setdefault(k, []).append(float(v))
    dim_avgs = {k: round(sum(v) / len(v), 1) for k, v in dim_totals.items()}

    tag_counts: dict[str, int] = {}
    for r in reviews:
        for t in (r["tags"] or []):
            tag_counts[t] = tag_counts.get(t, 0) + 1

    recommend_counts = {"yes": 0, "no": 0, "maybe": 0}
    for r in reviews:
        wr = r["would_recommend"]
        if wr in recommend_counts:
            recommend_counts[wr] += 1

    return {
        "reviews": reviews,
        "aggregate": {
            "avg_overall": round(avg_overall, 1),
            "review_count": len(reviews),
            "dimension_avgs": dim_avgs,
            "tag_counts": sorted(tag_counts.items(), key=lambda x: -x[1]),
            "recommend_counts": recommend_counts,
        },
    }


@app.get("/api/reviews/summary/{unitid}")
def api_review_summary(unitid: int, db: Session = Depends(get_db)):
    """Lightweight summary for CollegeCard / CompareColleges."""
    from sqlalchemy import func as sa_func

    row = (
        db.query(
            sa_func.count(Review.id).label("count"),
            sa_func.avg(Review.overall_rating).label("avg"),
        )
        .filter(Review.unitid == unitid)
        .first()
    )
    if not row or not row.count:
        return {"review_count": 0, "avg_rating": None}
    return {"review_count": row.count, "avg_rating": round(float(row.avg), 1)}


@app.post("/api/reviews")
def api_create_review(
    req: CreateReviewRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = db.query(Review).filter(
        Review.user_id == user.id, Review.unitid == req.unitid
    ).first()
    if existing:
        raise HTTPException(400, "You have already reviewed this college")

    if not (1 <= req.overall_rating <= 5):
        raise HTTPException(400, "Overall rating must be 1-5")
    if len(req.pros.strip()) < 20:
        raise HTTPException(400, "Pros must be at least 20 characters")
    if len(req.cons.strip()) < 20:
        raise HTTPException(400, "Cons must be at least 20 characters")

    review = Review(
        user_id=user.id,
        unitid=req.unitid,
        overall_rating=req.overall_rating,
        dimension_ratings=req.dimension_ratings,
        pros=req.pros,
        cons=req.cons,
        advice=req.advice,
        would_recommend=req.would_recommend,
        attendance_status=req.attendance_status,
        year=req.year,
        major=req.major,
        tags=req.tags,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    log_activity(db, user.id, "write_review", {"unitid": req.unitid, "overall_rating": req.overall_rating})
    return review.to_dict(username=user.username)


@app.delete("/api/reviews/{review_id}")
def api_delete_review(
    review_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(404, "Review not found")
    if review.user_id != user.id and not user.is_admin:
        raise HTTPException(403, "Not authorized")
    db.query(ReviewVote).filter(ReviewVote.review_id == review_id).delete()
    db.delete(review)
    db.commit()
    return {"deleted": True, "id": review_id}


@app.post("/api/reviews/{review_id}/vote")
def api_vote_review(
    review_id: int,
    vote: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if vote not in (1, -1):
        raise HTTPException(400, "Vote must be 1 or -1")
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(404, "Review not found")

    existing = db.query(ReviewVote).filter(
        ReviewVote.review_id == review_id, ReviewVote.user_id == user.id
    ).first()
    if existing:
        old_vote = existing.vote
        if old_vote == vote:
            raise HTTPException(400, "Already voted")
        if old_vote == 1:
            review.upvotes = max((review.upvotes or 0) - 1, 0)
        else:
            review.downvotes = max((review.downvotes or 0) - 1, 0)
        existing.vote = vote
    else:
        existing = ReviewVote(review_id=review_id, user_id=user.id, vote=vote)
        db.add(existing)

    if vote == 1:
        review.upvotes = (review.upvotes or 0) + 1
    else:
        review.downvotes = (review.downvotes or 0) + 1

    db.commit()
    return {"upvotes": review.upvotes, "downvotes": review.downvotes}


@app.get("/api/reviews/recent")
def api_recent_reviews(limit: int = 5, db: Session = Depends(get_db)):
    """Recent reviews across all colleges for the home feed."""
    rows = (
        db.query(Review, User.username)
        .outerjoin(User, Review.user_id == User.id)
        .order_by(Review.created_at.desc())
        .limit(limit)
        .all()
    )
    df = _get_colleges()
    results = []
    for r, uname in rows:
        d = r.to_dict(username=uname)
        col = df[df["UNITID"] == r.unitid]
        d["college_name"] = col.iloc[0]["INSTNM"] if not col.empty else f"College #{r.unitid}"
        results.append(d)
    return results


# ── Home Dashboard ───────────────────────────────────────────────────────────


@app.get("/api/home")
def api_home(
    user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    from sqlalchemy import func as sa_func

    def _community_counts():
        total_users = db.query(sa_func.count(User.id)).scalar() or 0
        total_reviews = db.query(sa_func.count(Review.id)).scalar() or 0
        colleges_reviewed = db.query(sa_func.count(sa_func.distinct(Review.unitid))).scalar() or 0
        return {
            "total_users": total_users,
            "total_reviews": total_reviews,
            "colleges_reviewed": colleges_reviewed,
        }

    # Logged-out users can still see community totals, but personal data is empty.
    if user is None:
        return {
            "shortlist": [],
            "activity": [],
            "progress": {
                "profile_complete": False,
                "has_match": False,
                "has_saved": False,
                "has_plan": False,
                "has_comparison": False,
                "has_review": False,
                "steps_done": 0,
                "total_steps": 6,
            },
            "community": _community_counts(),
        }

    saved = db.query(SavedCollege).filter(SavedCollege.user_id == user.id).order_by(SavedCollege.saved_at.desc()).limit(6).all()
    df = _get_colleges()
    shortlist = []
    for sc in saved:
        d = sc.to_dict()
        col = df[df["UNITID"] == sc.unitid]
        if not col.empty:
            r = col.iloc[0]
            d["college_name"] = r.get("INSTNM", "Unknown")
            # Ensure frontend receives either a real state abbrev string or null (not NaN).
            stabbr = r.get("STABBR")
            d["state"] = None if pd.isna(stabbr) else str(stabbr)
            d["adm_rate"] = None if pd.isna(r.get("ADM_RATE")) else float(r["ADM_RATE"])
        shortlist.append(d)

    recent = (
        db.query(UserActivity)
        .filter(UserActivity.user_id == user.id)
        .order_by(UserActivity.created_at.desc())
        .limit(5)
        .all()
    )
    activity = [
        {
            "id": a.id,
            "action_type": a.action_type,
            "metadata": a.metadata_,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in recent
    ]

    has_match = db.query(UserActivity).filter(
        UserActivity.user_id == user.id, UserActivity.action_type == "match_search"
    ).first() is not None
    has_plan = db.query(UserActivity).filter(
        UserActivity.user_id == user.id, UserActivity.action_type == "financial_plan"
    ).first() is not None
    has_saved = db.query(SavedCollege).filter(SavedCollege.user_id == user.id).first() is not None
    has_review = db.query(Review).filter(Review.user_id == user.id).first() is not None
    has_comparison = db.query(SavedComparison).filter(SavedComparison.user_id == user.id).first() is not None

    steps_done = sum([
        bool(user.profile_complete),
        has_match,
        has_saved,
        has_plan,
        has_comparison,
        has_review,
    ])

    return {
        "shortlist": shortlist,
        "activity": activity,
        "progress": {
            "profile_complete": bool(user.profile_complete),
            "has_match": has_match,
            "has_saved": has_saved,
            "has_plan": has_plan,
            "has_comparison": has_comparison,
            "has_review": has_review,
            "steps_done": steps_done,
            "total_steps": 6,
        },
        "community": _community_counts(),
    }


# ── Portfolio analytics (public ingest + admin read) ─────────────────────────

ANALYTICS_EVENT_TYPES = frozenset(
    {"landing", "page_view", "signup_complete", "login_success", "match_run"}
)


class AnalyticsEventRequest(BaseModel):
    session_id: str = Field(..., min_length=4, max_length=128)
    event_type: str = Field(..., min_length=1, max_length=64)
    utm_source: Optional[str] = Field(None, max_length=128)
    utm_medium: Optional[str] = Field(None, max_length=128)
    utm_campaign: Optional[str] = Field(None, max_length=256)
    utm_content: Optional[str] = Field(None, max_length=256)
    utm_term: Optional[str] = Field(None, max_length=256)
    referrer: Optional[str] = Field(None, max_length=2048)
    path: Optional[str] = Field(None, max_length=512)
    metadata: Optional[dict[str, Any]] = None


def _analytics_trim_str(val: Optional[str], max_len: int) -> Optional[str]:
    if val is None:
        return None
    s = val.strip()
    if not s:
        return None
    return s[:max_len]


def _analytics_trim_metadata(meta: Optional[dict]) -> Optional[dict]:
    if not meta:
        return None
    try:
        raw = json.dumps(meta)
    except (TypeError, ValueError):
        return None
    if len(raw) > 8000:
        return {"_truncated": True}
    return meta


@app.post("/api/analytics/event")
def post_analytics_event(
    body: AnalyticsEventRequest,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
):
    if body.event_type not in ANALYTICS_EVENT_TYPES:
        raise HTTPException(400, "Invalid event_type")

    row = PortfolioAnalyticsEvent(
        user_id=user.id if user else None,
        session_id=body.session_id.strip()[:128],
        event_type=body.event_type.strip()[:64],
        utm_source=_analytics_trim_str(body.utm_source, 128),
        utm_medium=_analytics_trim_str(body.utm_medium, 128),
        utm_campaign=_analytics_trim_str(body.utm_campaign, 256),
        utm_content=_analytics_trim_str(body.utm_content, 256),
        utm_term=_analytics_trim_str(body.utm_term, 256),
        referrer=_analytics_trim_str(body.referrer, 2048),
        path=_analytics_trim_str(body.path, 512),
        metadata_=_analytics_trim_metadata(body.metadata),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"ok": True, "id": row.id}


def _analytics_utm_nonempty_clause():
    from sqlalchemy import and_, or_

    return or_(
        and_(PortfolioAnalyticsEvent.utm_source.isnot(None), PortfolioAnalyticsEvent.utm_source != ""),
        and_(PortfolioAnalyticsEvent.utm_medium.isnot(None), PortfolioAnalyticsEvent.utm_medium != ""),
        and_(PortfolioAnalyticsEvent.utm_campaign.isnot(None), PortfolioAnalyticsEvent.utm_campaign != ""),
        and_(PortfolioAnalyticsEvent.utm_content.isnot(None), PortfolioAnalyticsEvent.utm_content != ""),
        and_(PortfolioAnalyticsEvent.utm_term.isnot(None), PortfolioAnalyticsEvent.utm_term != ""),
    )


def _analytics_clamp_days(days: int) -> int:
    return max(1, min(int(days or 30), 366))


def _require_admin(user: User):
    if not user.is_admin:
        raise HTTPException(401, "Admin access required")


@app.get("/api/admin/portfolio-analytics/summary")
def api_admin_portfolio_analytics_summary(
    days: int = 30,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from sqlalchemy import func as sa_func

    _require_admin(user)
    days = _analytics_clamp_days(days)
    since = datetime.utcnow() - timedelta(days=days)
    utm_nonempty = _analytics_utm_nonempty_clause()

    total_events = (
        db.query(sa_func.count(PortfolioAnalyticsEvent.id))
        .filter(PortfolioAnalyticsEvent.created_at >= since)
        .scalar()
        or 0
    )

    unique_sessions = (
        db.query(sa_func.count(sa_func.distinct(PortfolioAnalyticsEvent.session_id)))
        .filter(PortfolioAnalyticsEvent.created_at >= since)
        .scalar()
        or 0
    )

    unique_users = (
        db.query(sa_func.count(sa_func.distinct(PortfolioAnalyticsEvent.user_id)))
        .filter(
            PortfolioAnalyticsEvent.created_at >= since,
            PortfolioAnalyticsEvent.user_id.isnot(None),
        )
        .scalar()
        or 0
    )

    portfolio_session_list = [
        r[0]
        for r in (
            db.query(PortfolioAnalyticsEvent.session_id)
            .filter(PortfolioAnalyticsEvent.created_at >= since)
            .filter(utm_nonempty)
            .distinct()
            .all()
        )
    ]
    portfolio_sessions = len(portfolio_session_list)

    if portfolio_session_list:
        signups_portfolio = (
            db.query(sa_func.count(PortfolioAnalyticsEvent.id))
            .filter(
                PortfolioAnalyticsEvent.created_at >= since,
                PortfolioAnalyticsEvent.event_type == "signup_complete",
                PortfolioAnalyticsEvent.session_id.in_(portfolio_session_list),
            )
            .scalar()
            or 0
        )
        matches_portfolio = (
            db.query(sa_func.count(PortfolioAnalyticsEvent.id))
            .filter(
                PortfolioAnalyticsEvent.created_at >= since,
                PortfolioAnalyticsEvent.event_type == "match_run",
                PortfolioAnalyticsEvent.session_id.in_(portfolio_session_list),
            )
            .scalar()
            or 0
        )
        unique_users_portfolio = (
            db.query(sa_func.count(sa_func.distinct(PortfolioAnalyticsEvent.user_id)))
            .filter(
                PortfolioAnalyticsEvent.created_at >= since,
                PortfolioAnalyticsEvent.user_id.isnot(None),
                PortfolioAnalyticsEvent.session_id.in_(portfolio_session_list),
            )
            .scalar()
            or 0
        )
    else:
        signups_portfolio = 0
        matches_portfolio = 0
        unique_users_portfolio = 0

    conversion_rate = (
        round(signups_portfolio / portfolio_sessions, 4) if portfolio_sessions else 0.0
    )

    return {
        "days": days,
        "total_events": total_events,
        "unique_sessions": unique_sessions,
        "unique_users": unique_users,
        "portfolio_sessions": portfolio_sessions,
        "unique_users_portfolio": unique_users_portfolio,
        "signups_from_portfolio": signups_portfolio,
        "matches_from_portfolio": matches_portfolio,
        "signup_per_portfolio_session": conversion_rate,
    }


@app.get("/api/admin/portfolio-analytics/timeseries")
def api_admin_portfolio_analytics_timeseries(
    days: int = 30,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from sqlalchemy import cast, Date, func as sa_func

    _require_admin(user)
    days = _analytics_clamp_days(days)
    since = datetime.utcnow() - timedelta(days=days)
    key_types = ("landing", "page_view", "signup_complete", "login_success", "match_run")

    day_col = cast(PortfolioAnalyticsEvent.created_at, Date)
    rows = (
        db.query(
            day_col.label("d"),
            PortfolioAnalyticsEvent.event_type,
            sa_func.count(PortfolioAnalyticsEvent.id).label("cnt"),
        )
        .filter(
            PortfolioAnalyticsEvent.created_at >= since,
            PortfolioAnalyticsEvent.event_type.in_(key_types),
        )
        .group_by(day_col, PortfolioAnalyticsEvent.event_type)
        .order_by(day_col)
        .all()
    )

    # Build complete date range
    by_date: dict[str, dict[str, int]] = {}
    for i in range(days):
        d = (since.date() + timedelta(days=i)).isoformat()
        by_date[d] = {k: 0 for k in key_types}

    for r in rows:
        ds = r.d.isoformat() if hasattr(r.d, "isoformat") else str(r.d)
        if ds not in by_date:
            by_date[ds] = {k: 0 for k in key_types}
        if r.event_type in by_date[ds]:
            by_date[ds][r.event_type] = int(r.cnt)

    days_out = sorted(by_date.keys())
    series = [{"date": d, **by_date[d]} for d in days_out]
    return {"days": days, "series": series}


@app.get("/api/admin/portfolio-analytics/breakdown")
def api_admin_portfolio_analytics_breakdown(
    days: int = 30,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from sqlalchemy import func as sa_func

    _require_admin(user)
    days = _analytics_clamp_days(days)
    since = datetime.utcnow() - timedelta(days=days)

    utm_label = sa_func.coalesce(
        sa_func.nullif(sa_func.trim(PortfolioAnalyticsEvent.utm_source), ""),
        "(none)",
    )
    path_label = sa_func.coalesce(
        sa_func.nullif(sa_func.trim(PortfolioAnalyticsEvent.path), ""),
        "(none)",
    )

    utm_rows = (
        db.query(utm_label.label("k"), sa_func.count(PortfolioAnalyticsEvent.id).label("cnt"))
        .filter(PortfolioAnalyticsEvent.created_at >= since)
        .group_by(utm_label)
        .order_by(sa_func.count(PortfolioAnalyticsEvent.id).desc())
        .limit(15)
        .all()
    )
    path_rows = (
        db.query(path_label.label("k"), sa_func.count(PortfolioAnalyticsEvent.id).label("cnt"))
        .filter(PortfolioAnalyticsEvent.created_at >= since)
        .group_by(path_label)
        .order_by(sa_func.count(PortfolioAnalyticsEvent.id).desc())
        .limit(15)
        .all()
    )
    type_rows = (
        db.query(
            PortfolioAnalyticsEvent.event_type.label("k"),
            sa_func.count(PortfolioAnalyticsEvent.id).label("cnt"),
        )
        .filter(PortfolioAnalyticsEvent.created_at >= since)
        .group_by(PortfolioAnalyticsEvent.event_type)
        .order_by(sa_func.count(PortfolioAnalyticsEvent.id).desc())
        .all()
    )

    return {
        "days": days,
        "utm_source": [{"key": str(r.k), "count": int(r.cnt)} for r in utm_rows],
        "path": [{"key": str(r.k), "count": int(r.cnt)} for r in path_rows],
        "event_type": [{"key": str(r.k), "count": int(r.cnt)} for r in type_rows],
    }


# ── Admin ────────────────────────────────────────────────────────────────────


@app.get("/api/admin/dashboard")
def api_admin_dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user.is_admin:
        raise HTTPException(401, "Admin access required")
    users = db.query(User).all()
    return {"users": [u.to_dict() for u in users]}


@app.patch("/api/admin/users/{user_id}/toggle-admin")
def api_toggle_admin(user_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_admin(user)
    if user_id == user.id:
        raise HTTPException(400, "Cannot change your own admin status")
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(404, "User not found")
    if target.is_admin:
        admin_count = db.query(User).filter(User.is_admin == True).count()
        if admin_count <= 1:
            raise HTTPException(400, "Cannot demote the last admin")
    target.is_admin = not target.is_admin
    db.commit()
    db.refresh(target)
    return target.to_dict()


@app.delete("/api/admin/users/{user_id}")
def api_delete_user(user_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_admin(user)
    if user_id == user.id:
        raise HTTPException(400, "Cannot delete your own account")
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(404, "User not found")
    db.query(UserActivity).filter(UserActivity.user_id == user_id).delete()
    db.query(PortfolioAnalyticsEvent).filter(PortfolioAnalyticsEvent.user_id == user_id).delete()
    db.query(SavedCollege).filter(SavedCollege.user_id == user_id).delete()
    db.query(SavedPlan).filter(SavedPlan.user_id == user_id).delete()
    db.query(SavedComparison).filter(SavedComparison.user_id == user_id).delete()
    review_ids = [r.id for r in db.query(Review.id).filter(Review.user_id == user_id).all()]
    if review_ids:
        db.query(ReviewVote).filter(ReviewVote.review_id.in_(review_ids)).delete(synchronize_session=False)
    db.query(Review).filter(Review.user_id == user_id).delete()
    db.query(ReviewVote).filter(ReviewVote.user_id == user_id).delete()
    db.delete(target)
    db.commit()
    return {"deleted": True, "id": user_id}


@app.get("/api/admin/stats")
def api_admin_stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from sqlalchemy import func as sa_func, text
    from collections import Counter

    _require_admin(user)

    total_users = db.query(sa_func.count(User.id)).scalar() or 0
    profiles_complete = db.query(sa_func.count(User.id)).filter(User.profile_complete == True).scalar() or 0

    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    signups_last_7 = (
        db.query(sa_func.count(UserActivity.id))
        .filter(UserActivity.action_type == "signup", UserActivity.created_at >= seven_days_ago)
        .scalar() or 0
    )

    total_matches = (
        db.query(sa_func.count(UserActivity.id))
        .filter(UserActivity.action_type == "match_search")
        .scalar() or 0
    )
    total_plans = (
        db.query(sa_func.count(UserActivity.id))
        .filter(UserActivity.action_type == "financial_plan")
        .scalar() or 0
    )

    match_rows = (
        db.query(UserActivity.metadata_)
        .filter(UserActivity.action_type == "match_search", UserActivity.metadata_ != None)
        .all()
    )
    college_counter: Counter = Counter()
    llm_count = 0
    fallback_count = 0
    for (meta,) in match_rows:
        if not meta:
            continue
        name = meta.get("top_college")
        if name:
            college_counter[name] += 1
        if meta.get("used_llm") or meta.get("used_gemini"):
            llm_count += 1
        else:
            fallback_count += 1

    most_searched = college_counter.most_common(1)[0][0] if college_counter else None
    total_g_f = llm_count + fallback_count
    ratio = f"{llm_count}:{fallback_count}" if total_g_f else "0:0"

    return {
        "total_users": total_users,
        "profiles_complete": profiles_complete,
        "signups_last_7_days": signups_last_7,
        "total_matches_run": total_matches,
        "total_financial_plans_run": total_plans,
        "most_searched_college": most_searched,
        "groq_vs_fallback_ratio": ratio,
    }


@app.get("/api/admin/activity")
def api_admin_activity(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_admin(user)

    rows = (
        db.query(UserActivity, User.username)
        .outerjoin(User, UserActivity.user_id == User.id)
        .order_by(UserActivity.created_at.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id": act.id,
            "user_id": act.user_id,
            "username": uname,
            "action_type": act.action_type,
            "metadata": act.metadata_,
            "created_at": act.created_at.isoformat() if act.created_at else None,
        }
        for act, uname in rows
    ]


@app.get("/api/admin/signups-over-time")
def api_admin_signups_over_time(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from sqlalchemy import func as sa_func, text

    _require_admin(user)

    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    date_col = sa_func.date(UserActivity.created_at)
    rows = (
        db.query(
            date_col.label("date"),
            sa_func.count(UserActivity.id).label("count"),
        )
        .filter(UserActivity.action_type == "signup", UserActivity.created_at >= thirty_days_ago)
        .group_by(date_col)
        .order_by(date_col)
        .all()
    )
    return [{"date": str(r.date), "count": r.count} for r in rows]


@app.get("/api/admin/match-analytics")
def api_admin_match_analytics(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from collections import Counter

    _require_admin(user)

    match_rows = (
        db.query(UserActivity.metadata_)
        .filter(UserActivity.action_type == "match_search", UserActivity.metadata_ != None)
        .all()
    )

    college_counter: Counter = Counter()
    sim_scores: list[float] = []
    for (meta,) in match_rows:
        if not meta:
            continue
        name = meta.get("top_college")
        if name:
            college_counter[name] += 1
        score = meta.get("similarity_score")
        if score is not None:
            try:
                sim_scores.append(float(score))
            except (TypeError, ValueError):
                pass

    avg_sim = round(sum(sim_scores) / len(sim_scores), 4) if sim_scores else None
    top_colleges = [{"college": name, "count": cnt} for name, cnt in college_counter.most_common(10)]

    return {
        "top_matched_colleges": top_colleges,
        "average_similarity_score": avg_sim,
        "total_match_searches": len(match_rows),
    }


@app.get("/api/admin/profile-insights")
def api_admin_profile_insights(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from collections import Counter

    _require_admin(user)

    users = db.query(User).filter(User.profile_complete == True).all()

    gpa_buckets = Counter()
    major_counter = Counter()
    state_counter = Counter()
    size_counter = Counter()

    for u in users:
        if u.gpa is not None:
            bucket = f"{int(u.gpa)}.0-{int(u.gpa)}.9" if u.gpa < 4.0 else "4.0"
            gpa_buckets[bucket] += 1
        if u.intended_major:
            major_counter[u.intended_major] += 1
        if u.preferred_state:
            state_counter[u.preferred_state] += 1
        if u.school_size:
            size_counter[u.school_size] += 1

    return {
        "total_profiles": len(users),
        "gpa_distribution": dict(gpa_buckets),
        "major_counts": [{"major": m, "count": c} for m, c in major_counter.most_common(15)],
        "state_counts": [{"state": s, "count": c} for s, c in state_counter.most_common(15)],
        "school_size_breakdown": dict(size_counter),
    }


# ── Serve React frontend (production) ───────────────────────────────────────

STATIC_DIR = Path(__file__).resolve().parent / "frontend" / "dist"

if STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve the React SPA for any non-API route."""
        file = STATIC_DIR / full_path
        if file.is_file():
            return FileResponse(str(file))
        return FileResponse(str(STATIC_DIR / "index.html"))
