"""FastAPI endpoints for read-only project reviews."""
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StringConstraints
from sqlalchemy.exc import SQLAlchemyError

from business_scope_llm import BusinessScopeLLM
from ledger_service import FIELDS, POLICIES, RULE_VERSION, LedgerClient
from owner_service import OWNER_POLICY, TianyanchaClient
from station_service import STATION_POLICY
from auth import TokenVerifier, require_user

ROOT = Path(__file__).resolve().parent.parent


class ReviewRequest(BaseModel):
    projectCode: Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=255)]


def configured_client():
    document = os.environ.get("LEDGER_CREDENTIALS_DOC")
    settings = ROOT / "local-data/connection.json"
    if document is None and settings.is_file():
        document = json.loads(settings.read_text(encoding="utf-8")).get("credentialsDocument")
    if not document or not Path(document).is_file():
        return None
    classifier = BusinessScopeLLM.from_settings(ROOT / "local-data/llm.json")
    tianyancha = TianyanchaClient.from_settings(ROOT / "local-data/tianyancha.json", classifier=classifier)
    return LedgerClient(Path(document), tianyancha=tianyancha)


def create_app(client_factory=configured_client):
    @asynccontextmanager
    async def lifespan(app):
        app.state.ledger = client_factory()
        try:
            yield
        finally:
            if app.state.ledger is not None:
                app.state.ledger.close()

    app = FastAPI(title="流程自动审批", version="0.1.0", lifespan=lifespan,
                  dependencies=[Depends(require_user)])
    app.state.token_verifier = TokenVerifier()

    @app.middleware("http")
    async def request_headers(request: Request, call_next):
        if request.method == "POST" and request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            # Next.js rewrites retain the public host in x-forwarded-host.
            host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
            scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
            if origin and origin != f"{scheme}://{host}":
                return JSONResponse({"message": "请求来源不匹配"}, status_code=403)
            if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
                return JSONResponse({"message": "请求须使用 JSON"}, status_code=415)
            size = 0
            chunks = []
            async for chunk in request.stream():
                chunks.append(chunk)
                size += len(chunk)
                if size > 4096:
                    return JSONResponse({"message": "请求内容长度无效"}, status_code=400)
            request._body = b"".join(chunks)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        return JSONResponse({"message": "请输入有效的项目编号（1 至 255 个字符）。"}, status_code=400)

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return JSONResponse({"message": error.detail}, status_code=error.status_code, headers=error.headers)

    @app.exception_handler(SQLAlchemyError)
    @app.exception_handler(OSError)
    async def database_error(request, error):
        return JSONResponse({"message": "台账查询失败，本次检查未完成。请检查数据库连接后重试。"}, status_code=503)

    @app.exception_handler(Exception)
    async def unexpected_error(request, error):
        return JSONResponse({"message": "本次检查未完成，未生成查重结论。"}, status_code=500)

    @app.get("/api/me")
    def current_user(user: Annotated[dict, Depends(require_user)]):
        return user

    @app.get("/api/health")
    def health(request: Request):
        return {"status": "ready" if request.app.state.ledger else "unconfigured", "policyVersion": RULE_VERSION}

    @app.get("/api/policy")
    def policy():
        return {"version": RULE_VERSION, "fields": FIELDS, "policies": POLICIES,
                "ownerPolicy": OWNER_POLICY, "stationPolicy": STATION_POLICY}

    @app.post("/api/project-reviews")
    def review(body: ReviewRequest, request: Request):
        client = request.app.state.ledger
        if client is None:
            return JSONResponse({"message": "本地数据库连接尚未配置，请配置后重启服务。"}, status_code=503)
        report = client.review(body.projectCode)
        return JSONResponse(report, status_code={"not_found": 404, "ambiguous": 409}.get(report["status"], 200))

    return app


app = create_app()
