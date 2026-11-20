"""Webes API: gyorsan feladatazonosítót ad, a feldolgozást a worker végzi. Egyfelhasználós, bearer-tokenes hitelesítés."""
from __future__ import annotations

import hmac

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, Field

from .config import Settings
from .db import Store
from .models import JobStatus, Limits, ResearchPlan, ResearchReport
from .planner import effective_limits
from .report import to_csv, to_json, to_markdown


class JobRequest(BaseModel):
    request: str = Field(min_length=3, max_length=4000)
    platforms: list[str] = []
    languages: list[str] = ["hu", "en"]
    limits: Limits | None = None


def create_app(store: Store, settings: Settings) -> FastAPI:
    app = FastAPI(title="Videós kutatóügynök", version="1.0")

    def auth(authorization: str | None = Header(default=None)) -> None:
        if not settings.api_token:
            if settings.mode == "production":
                raise HTTPException(503, "Az API-token nincs beállítva")
            return                                      # csak dev módban, token nélkül
        supplied = (authorization or "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(supplied.encode(), settings.api_token.reveal().encode()):
            raise HTTPException(401, "Hitelesítés szükséges")

    def view(jid: str) -> dict:
        job = store.get_job(jid)
        if not job:
            raise HTTPException(404, "Nincs ilyen feladat")
        plan = store.get_field(jid, "plan")
        return {"id": job.id, "status": job.status.value, "request": job.request, "platforms": [p.value for p in job.platforms],
                "estimated_cost": job.estimated_cost, "recorded_cost": job.recorded_cost,
                "cost_note": "az estimated_cost becslés, a recorded_cost csak a ténylegesen ismert költség",
                "plan": ResearchPlan.model_validate_json(plan).model_dump(mode="json") if plan else None,
                "error": store.get_field(jid, "error"),
                "steps": {k: {"status": v[0].value, **v[1]} for k, v in store.get_steps(jid).items()}}

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.post("/jobs", status_code=202, dependencies=[Depends(auth)])
    def create_job(body: JobRequest, response: Response, idempotency_key: str | None = Header(default=None)) -> dict:
        if idempotency_key is not None and not (8 <= len(idempotency_key) <= 128):
            raise HTTPException(422, "Az Idempotency-Key 8–128 karakter lehet")
        bad = [p for p in body.platforms if p not in settings.allowed_platforms]
        if bad:
            raise HTTPException(422, f"nem engedélyezett platform: {bad}")
        if any(l not in ("hu", "en") for l in body.languages):
            raise HTTPException(422, "támogatott nyelvek: hu, en")
        limits = effective_limits(settings, body.limits)
        try:
            job, created = store.create_job(body.request, body.platforms, body.languages, limits, idempotency_key)
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        if not created:
            response.status_code = 200
        return {"job_id": job.id, "status": job.status.value, "created": created}

    @app.get("/jobs/{jid}", dependencies=[Depends(auth)])
    def get_job(jid: str) -> dict:
        return view(jid)

    @app.post("/jobs/{jid}/approve", dependencies=[Depends(auth)])
    def approve(jid: str) -> dict:
        job = store.get_job(jid)
        if not job:
            raise HTTPException(404, "Nincs ilyen feladat")
        plan = store.get_field(jid, "plan")
        if job.status != JobStatus.awaiting_approval or not plan:
            raise HTTPException(409, f"Jóváhagyás csak awaiting_approval állapotban lehetséges (jelenleg: {job.status.value})")
        store.set_status(jid, JobStatus.queued, approved_plan=plan)
        return view(jid)

    @app.post("/jobs/{jid}/cancel", dependencies=[Depends(auth)])
    def cancel(jid: str) -> dict:
        st = store.request_cancel(jid)
        if st is None:
            raise HTTPException(404, "Nincs ilyen feladat")
        v = view(jid)
        v["cancel_note"] = ("Best effort megszakítás: a már elindított szolgáltatói művelet leállítása nem azonnali és nem garantált; "
                            "a worker a következő lépéshatárnál áll meg.")
        return v

    @app.get("/jobs/{jid}/report", dependencies=[Depends(auth)])
    def report(jid: str, format: str = "json"):
        job = store.get_job(jid)
        raw = store.get_field(jid, "report") if job else None
        if not job:
            raise HTTPException(404, "Nincs ilyen feladat")
        if not raw:
            raise HTTPException(409, f"A jelentés még nem készült el (állapot: {job.status.value})")
        r = ResearchReport.model_validate_json(raw)
        if format == "markdown":
            return Response(to_markdown(r, job), media_type="text/markdown; charset=utf-8")
        if format == "csv":
            return Response(to_csv(r), media_type="text/csv; charset=utf-8")
        if format == "json":
            return Response(to_json(r), media_type="application/json")
        raise HTTPException(422, "format: json | markdown | csv")

    return app
