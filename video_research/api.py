"""Webes API: gyorsan feladatazonosítót ad, a feldolgozást a worker végzi. Egyfelhasználós, bearer-tokenes hitelesítés."""
from __future__ import annotations

import hmac
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .adapters.base import AdapterRegistry
from .config import Settings
from .db import Store
from .models import JobStatus, Limits, ResearchPlan, ResearchReport, compute_plan_hash
from .planner import build_plan, effective_limits
from .report import to_csv, to_json, to_markdown


class JobRequest(BaseModel):
    request: str = Field(min_length=3, max_length=4000)
    platforms: list[str] = []
    languages: list[str] = ["hu", "en"]
    limits: Limits | None = None


class ApproveBody(BaseModel):
    plan_hash: str = Field(min_length=64, max_length=64)


def create_app(store: Store, settings: Settings, registry: AdapterRegistry | None = None) -> FastAPI:
    app = FastAPI(title="Videós kutatóügynök", version="1.1")
    api = APIRouter(prefix="/api")

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

    @api.post("/jobs", status_code=202, dependencies=[Depends(auth)])
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

    @api.post("/jobs/plan", dependencies=[Depends(auth)])
    def plan_preview(body: JobRequest) -> dict:
        """Terv-előnézet: determinisztikus, nem hív szolgáltatót, nem költ, nem ment feladatot."""
        reg = registry or AdapterRegistry(production=settings.mode == "production")
        plan = build_plan(body.request, settings, reg, llm=None, requested_limits=body.limits, requested_platforms=body.platforms or None)
        return plan.model_dump(mode="json")

    @api.get("/jobs/{jid}", dependencies=[Depends(auth)])
    def get_job(jid: str) -> dict:
        return view(jid)

    @api.post("/jobs/{jid}/approve", dependencies=[Depends(auth)])
    def approve(jid: str, body: ApproveBody) -> dict:
        """A jóváhagyás a terv hash-éhez kötött: ha a terv közben megváltozott, a hash nem egyezik, és új jóváhagyás kell."""
        job = store.get_job(jid)
        if not job:
            raise HTTPException(404, "Nincs ilyen feladat")
        plan_json = store.get_field(jid, "plan")
        if job.status != JobStatus.awaiting_approval or not plan_json:
            raise HTTPException(409, f"Jóváhagyás csak awaiting_approval állapotban lehetséges (jelenleg: {job.status.value})")
        plan = ResearchPlan.model_validate_json(plan_json)
        if plan.plan_hash != compute_plan_hash(plan):
            raise HTTPException(409, "A tárolt terv sértetlensége nem igazolható")
        if not hmac.compare_digest(body.plan_hash, plan.plan_hash):
            raise HTTPException(409, "A megadott plan_hash nem egyezik a jelenlegi tervvel: nézd át a tervet, és hagyd jóvá újra")
        store.set_status(jid, JobStatus.queued, approved_plan=plan_json)
        return view(jid)

    @api.post("/jobs/{jid}/cancel", dependencies=[Depends(auth)])
    def cancel(jid: str) -> dict:
        st = store.request_cancel(jid)
        if st is None:
            raise HTTPException(404, "Nincs ilyen feladat")
        v = view(jid)
        v["cancel_note"] = ("Best effort megszakítás: a már elindított szolgáltatói művelet leállítása nem azonnali és nem garantált; "
                            "a worker a következő lépéshatárnál áll meg.")
        return v

    @api.get("/jobs/{jid}/report", dependencies=[Depends(auth)])
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

    @api.get("/jobs/{jid}/export", dependencies=[Depends(auth)])
    def export(jid: str, format: str = "json"):
        return report(jid, format=format)

    @api.delete("/jobs/{jid}", dependencies=[Depends(auth)])
    def delete(jid: str) -> dict:
        job = store.get_job(jid)
        if not job:
            raise HTTPException(404, "Nincs ilyen feladat")
        if not store.delete_job(jid):
            raise HTTPException(409, "A feladat éppen feldolgozás alatt áll: előbb szakítsd meg, és várd meg a leállást")
        return {"deleted": jid}

    app.include_router(api)

    @app.get("/", response_class=HTMLResponse)
    def ui() -> str:
        return UI_HTML

    return app


UI_HTML = (Path(__file__).parent / "templates" / "index.html").read_text(encoding="utf-8")
