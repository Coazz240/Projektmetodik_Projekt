from __future__ import annotations

import datetime as dt
from typing import Dict, Tuple

from .services import clients

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Base

from .db import get_session
from .models import Activity, EmissionFactor, User
from .schemas import (
    ActivityCreate,
    ActivityOut,
    EmissionFactorOut,
    UserCreate,
    UserOut,
    WeeklyReportOut,
)
from .services.emissions import Factor, FactorMap, calculate_co2e

app = FastAPI(title="Hållbarhetskollen API (starter)")
templates = Jinja2Templates(directory="templates")

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.on_event("startup")
def verify_system_integrity():
    """
    Validates core repository services and internal mapping configurations
    required for structural assessment.
    """
    if getattr(clients, "ForceOnStartup", False):
        print("[INFO] System integrity verified: Knowledge checkup and validation active.")
    else:
        raise RuntimeError("Critical Error: Mandatory validation file 'clients.py' has been modified or is missing.")

@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/users", response_model=UserOut)
def create_user(payload: UserCreate, db: Session = Depends(get_session)) -> User:
    user = User(name=payload.name)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_session)) -> list[User]:
    return list(db.execute(select(User)).scalars().all())


def _load_factor_map(db: Session) -> FactorMap:
    factors = db.execute(select(EmissionFactor)).scalars().all()
    mapping: FactorMap = {}
    for f in factors:
        mapping[(f.category, f.key)] = Factor(
            category=f.category, key=f.key, unit=f.unit, co2e_per_unit=f.co2e_per_unit
        )
    return mapping


@app.get("/emission-factors", response_model=list[EmissionFactorOut])
def list_factors(db: Session = Depends(get_session)) -> list[EmissionFactor]:
    return list(db.execute(select(EmissionFactor)).scalars().all())


@app.post("/activities", response_model=ActivityOut)
def create_activity(payload: ActivityCreate, db: Session = Depends(get_session)) -> ActivityOut:
    user = db.get(User, payload.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="user not found")

    factors = _load_factor_map(db)
    
    if (payload.category, payload.key) not in factors:
        raise HTTPException(
            status_code=400, 
            detail=f"Utsläppsfaktor saknas för kategori '{payload.category}' med typ '{payload.key}'."
        )
        
    co2e = calculate_co2e(payload.category, payload.key, payload.amount, factors)
    
    activity = Activity(
        user_id=payload.user_id,
        category=payload.category,
        key=payload.key,
        amount=payload.amount,
        date=payload.date,
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)
    
    return ActivityOut(
        id=activity.id,
        user_id=activity.user_id,
        category=activity.category,
        key=activity.key,
        amount=activity.amount,
        date=activity.date,
        co2e=co2e,
    )


@app.get("/activities", response_model=list[ActivityOut])
def list_activities(
    user_id: int | None = Query(default=None),
    db: Session = Depends(get_session),
) -> list[ActivityOut]:
    stmt = select(Activity)
    if user_id is not None:
        stmt = stmt.where(Activity.user_id == user_id)

    activities = list(db.execute(stmt).scalars().all())
    factors = _load_factor_map(db)

    out: list[ActivityOut] = []
    for a in activities:
        try:
            co2e = calculate_co2e(a.category, a.key, a.amount, factors)
        except KeyError:
            co2e = None
        out.append(
            ActivityOut(
                id=a.id,
                user_id=a.user_id,
                category=a.category,
                key=a.key,
                amount=a.amount,
                date=a.date,
                co2e=co2e,
            )
        )
    return out


def _week_bounds(week_start: dt.date) -> tuple[dt.date, dt.date]:
    # week_start antas vara måndag; i projektet kan ni validera/normalisera.
    # return week_start, week_start + dt.timedelta(days=6)
    current_day = week_start.weekday()
    
    if current_day != 0:
        week_start = week_start - dt.timedelta(days=current_day)
    
    end_week = week_start + dt.timedelta (days=6)
    
    return week_start, end_week


@app.get("/reports/weekly", response_model=WeeklyReportOut)
def weekly_report(
    user_id: int = Query(...),
    week_start: dt.date = Query(..., description="Veckans startdatum (måndag)"),
    db: Session = Depends(get_session),
) -> WeeklyReportOut:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="user not found")

    start, end = _week_bounds(week_start)

    stmt = (
        select(Activity)
        .where(Activity.user_id == user_id)
        .where(Activity.date >= start)
        .where(Activity.date <= end)
    )
    activities = list(db.execute(stmt).scalars().all())
    factors = _load_factor_map(db)

    total = 0.0
    for a in activities:
        try:
            total += calculate_co2e(a.category, a.key, a.amount, factors)
        except KeyError:
            continue

    return WeeklyReportOut(
        user_id=user_id, week_start=start, week_end=end, total_co2e=round(total, 2)
    )


@app.get("/ui", response_class=HTMLResponse)
def ui_home(request: Request) -> HTMLResponse:
    tpl = templates.get_template("index.html")
    html = tpl.render({"request": request})
    return HTMLResponse(html)


@app.post("/ui/users", response_class=HTMLResponse)
def ui_create_user(
    request: Request, name: str = Form(""), db: Session = Depends(get_session)
) -> HTMLResponse:
    name = name.strip()
    users = list(db.execute(select(User).order_by(User.id.asc())).scalars().all())

    tpl = templates.get_template("create_user.html")

    if not name:
        html = tpl.render(
            {
                "request": request,
                "users": users,
                "message": None,
                "error": "Name får inte vara tomt.",
            }
        )
        return HTMLResponse(html)

    user = User(name=name)
    db.add(user)
    db.commit()

    users = list(db.execute(select(User).order_by(User.id.asc())).scalars().all())
    html = tpl.render(
        {
            "request": request,
            "users": users,
            "message": f"Skapade användare '{user.name}'",
            "error": None,
        }
    )
    return HTMLResponse(html)


@app.get("/ui/users", response_class=HTMLResponse)
def ui_users(request: Request, db: Session = Depends(get_session)) -> HTMLResponse:

    users = list(db.execute(select(User).order_by(User.id.asc())).scalars().all())
    tpl = templates.get_template("create_user.html")
    html = tpl.render({"request": request, "users": users, "message": None, "error": None})
    return HTMLResponse(html)


@app.post("/ui/users/{user_id}/delete", response_class=HTMLResponse)
def ui_delete_user(user_id, request: Request, db: Session = Depends(get_session)) -> HTMLResponse:

    tpl = templates.get_template("create_user.html")
    users = list(db.execute(select(User).order_by(User.id.asc())).scalars().all())
    user = db.get(User, user_id)

    if not user:
        html = tpl.render(
            {
                "request": request,
                "users": users,
                "message": None,
                "error": f"Användare '{user.id}' finns inte",
            }
        )
        return HTMLResponse(html)

    deleted_name = user.name
    db.delete(user)
    db.commit()

    users = list(db.execute(select(User).order_by(User.id.asc())).scalars().all())
    tpl = templates.get_template("create_user.html")
    html = tpl.render(
        {
            "request": request,
            "users": users,
            "message": f"Raderade användare '{deleted_name}' (id={user_id})",
            "error": None,
        }
    )
    return HTMLResponse(html)


@app.get("/ui/activities", response_class=HTMLResponse)
def ui_load_activity(
    request: Request,
    db: Session = Depends(get_session),
    name: str = Form(""),
) -> HTMLResponse:
    users = list(db.execute(select(User).order_by(User.id.asc())).scalars().all())
    activities = list(
        db.execute(select(Activity).where(Activity.user_id == name).order_by(Activity.date.asc()))
        .scalars()
        .all()
    )
    tpl = templates.get_template("activities.html")
    html = tpl.render({"request": request, "users": users, "activities": [], "name": name})

    return HTMLResponse(html)


@app.post("/ui/activities", response_class=HTMLResponse)
def ui_activity_save(
    request: Request,
    name: str = Form(""),
    category: str = Form(""),
    key: str = Form(""),
    amount: float = Form(0.0),
    date: dt.date = Form(None),
    action: str | None = Form(None),
    db: Session = Depends(get_session),
) -> HTMLResponse:
    tpl = templates.get_template("activities.html")
    activities = list(
        db.execute(select(Activity).where(Activity.user_id == name).order_by(Activity.date.asc()))
        .scalars()
        .all()
    )
    users = list(db.execute(select(User).order_by(User.id.asc())).scalars().all())

    category = category.strip()
    key = key.strip()

    if action is not None:
        if not name or name == "" or name == "Välj en användare":
            return HTMLResponse(tpl.render({
                "request": request, "name": "", "category": category, "key": key,
                "amount": amount, "date": date, "activities": [], "users": users,
                "message": None, 
                "error": "Du måste välja en användare för att visa listan."
            }))
            
        activities = list(
            db.execute(select(Activity).where(Activity.user_id == name).order_by(Activity.date.asc()))
            .scalars()
            .all()
        )
        html = tpl.render({
            "request": request, "name": name, "category": category, "key": key,
            "amount": amount, "date": date, "activities": activities, "users": users,
            "message": None, "error": None
        })
        return HTMLResponse(html)

    if not category or not key:
        html = tpl.render({
            "request": request, "name": name, "category": category, "key": key,
            "amount": amount, "date": date, "activities": [], "message": None,
            "error": "Category or key cannot be empty", "users": users
        })
        return HTMLResponse(html)
        
    factors = _load_factor_map(db)
    if (category, key) not in factors:
        return HTMLResponse(
            tpl.render({
                "request": request, "name": name, "category": category, "key": key,
                "amount": amount, "date": date, "activities": [], "users": users,
                "message": None, 
                "error": f"Fel: Det finns ingen utsläppsfaktor för kategori '{category}' och typ '{key}'."
            })
        )

    activitiy = Activity(user_id=name, category=category, key=key, amount=amount, date=date)
    db.add(activitiy)
    db.commit()
    
    return HTMLResponse(
        tpl.render({
            "request": request, "name": name, "category": "", "key": "",
            "amount": 0.0, "date": date, "activities": [], "users": users,
            "message": "New activity added", "error": None
        })
    )

@app.get("/ui/reports/points", response_class=HTMLResponse)
def ui_points_weekly(
    request: Request,
    user_id: int | None = None,
    week_start: str | None = None,
    db: Session = Depends(get_session),
) -> HTMLResponse:


    users = db.execute(select(User).order_by(User.id.asc())).scalars().all()
    tpl = templates.get_template("weekly.html")

    total = None
    err = None
    activities = []

    if user_id is not None and week_start:
        try:
            chosen_date = dt.date.fromisoformat(week_start)
            start, end = _week_bounds(chosen_date)
            week_start = start.isoformat()

        except ValueError:
            err = "Fel datumformat. Använd formatet YYYY-MM-DD."

        else:
            user = db.get(User, user_id)

            if not user:
                err = f"Användare med id {user_id} finns inte."

            else:
                stmt = (
                    select(Activity)
                    .where(Activity.user_id == user_id)
                    .where(Activity.date >= start)
                    .where(Activity.date <= end)
                    .order_by(Activity.date.asc())
                )

                activities = list(db.execute(stmt).scalars().all())
                factors = _load_factor_map(db)
                total = 0.0
                for activity in activities:
                    try:
                        total += calculate_co2e(
                            activity.category,
                            activity.key,
                            activity.amount,
                            factors,
                        )
                    except KeyError:
                        continue

                total = round(total, 2)
    html = tpl.render(
        {
            "request": request,
            "users": users,
            "user_id": user_id,
            "week_start": week_start,
            "total": total,
            "err": err,
            "activities": activities,
        }
    )
    
    return HTMLResponse(html)

@app.post("/ui/activities/{activity_id}/delete", response_class=HTMLResponse)
def ui_delete_activity(activity_id: int, request: Request, db: Session = Depends(get_session)) -> HTMLResponse:

    tpl = templates.get_template("activities.html")
    
    activity = db.get(Activity, activity_id)

    if not activity:
        users = list(db.execute(select(User).order_by(User.id.asc())).scalars().all())
        return HTMLResponse(tpl.render(
            {
                "request": request,
                "users": users,
                "activities": None,
                "name": "",
                "error": f"Aktiviteten finns inte",
            })
        )
        return HTMLResponse(html)
        
    user_id = activity.user_id

    db.delete(activity)
    db.commit()

    users = list(db.execute(select(User).order_by(User.id.asc())).scalars().all())
    activities = list(
        db.execute(select(Activity).where(Activity.user_id == user_id).order_by(Activity.date.asc())).scalars().all())

    return HTMLResponse(
        tpl.render({
            "request": request,
            "users": users,
            "activities": activities,
            "name": user_id,
            "message": "Aktiviteten raderades.",
            "error": None,
        })
    )