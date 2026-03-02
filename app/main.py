from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse

from app.api.routes.health import router as health_router
from app.api.routes.translate import router as translate_router
from app.core.auth import require_basic_auth


app = FastAPI(
    title="Doc Generator API",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    dependencies=[Depends(require_basic_auth)],
)
app.include_router(health_router)
app.include_router(translate_router)


@app.get("/openapi.json", include_in_schema=False, dependencies=[Depends(require_basic_auth)])
def openapi_schema() -> JSONResponse:
    return JSONResponse(app.openapi())


@app.get("/docs", include_in_schema=False, dependencies=[Depends(require_basic_auth)])
def docs() -> object:
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="Doc Generator API - Swagger UI",
    )
