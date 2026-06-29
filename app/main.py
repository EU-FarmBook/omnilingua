from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse

from app.api.routes.health import router as health_router
from app.api.routes.translate import router as translate_router
from app.core.auth import require_basic_auth


DESCRIPTION = """
**Structure-preserving document translation** across the 24 official EU languages.

Use `POST /translate/document` to translate supported files while preserving layout,
fonts, and formatting as closely as possible.

### Supported file types

- `.pdf`
- `.txt`
- `.doc`, `.docx`
- `.ppt`, `.pptx`

### Translation backend

Use the optional `engine` field to choose `llm`, `deepl`, or `adaptive`. If omitted,
the server uses its configured default.

- `llm` — self-hosted OpenAI-compatible translation backend.
- `deepl` — DeepL only.
- `adaptive` — DeepL first, with automatic fallback to the LLM.
"""

app = FastAPI(
    title="OmniLingua API",
    version="1.0.0",
    description=DESCRIPTION,
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
        title="OmniLingua API - Swagger UI",
    )
    body = response.body.decode("utf-8")
    file_accept_script = """
<script>
(() => {
  const DOCUMENT_ACCEPT = '.pdf,.txt,.doc,.docx,.ppt,.pptx,application/pdf,text/plain,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/msword,application/vnd.openxmlformats-officedocument.presentationml.presentation,application/vnd.ms-powerpoint';

  const applyFileAccept = () => {
    document.querySelectorAll('.opblock').forEach((block) => {
      const path = block.querySelector('.opblock-summary-path');
      const input = block.querySelector('input[type="file"]');
      if (path?.textContent === '/translate/document' && input) {
        input.setAttribute('accept', DOCUMENT_ACCEPT);
      }
    });
  };
  applyFileAccept();
  const observer = new MutationObserver(applyFileAccept);
  observer.observe(document.body, { childList: true, subtree: true });
})();
</script>
"""
    body = body.replace("</body>", f"{file_accept_script}</body>")
    passthrough_headers = {
        key: value
        for key, value in response.headers.items()
        if key.lower() != "content-length"
    }
    return HTMLResponse(body, status_code=response.status_code, headers=passthrough_headers)
