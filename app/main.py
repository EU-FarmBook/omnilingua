from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse

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
    response = get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="Doc Generator API - Swagger UI",
    )
    body = response.body.decode("utf-8")
    pdf_accept_script = """
<script>
(() => {
  const PDF_ACCEPT = '.pdf,application/pdf';
  const DOCUMENT_ACCEPT = '.pdf,.txt,.doc,.docx,.ppt,.pptx,application/pdf,text/plain,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/msword,application/vnd.openxmlformats-officedocument.presentationml.presentation,application/vnd.ms-powerpoint';

  const applyFileAccept = () => {
    document.querySelectorAll('.opblock').forEach((block) => {
      const path = block.querySelector('.opblock-summary-path');
      const input = block.querySelector('input[type="file"]');
      if (!path || !input) {
        return;
      }
      if (path.textContent === '/translate/document') {
        input.setAttribute('accept', DOCUMENT_ACCEPT);
      } else {
        input.setAttribute('accept', PDF_ACCEPT);
      }
    });
  };
  applyFileAccept();
  const observer = new MutationObserver(applyFileAccept);
  observer.observe(document.body, { childList: true, subtree: true });
})();
</script>
"""
    body = body.replace("</body>", f"{pdf_accept_script}</body>")
    return HTMLResponse(body, status_code=response.status_code, headers=dict(response.headers))
