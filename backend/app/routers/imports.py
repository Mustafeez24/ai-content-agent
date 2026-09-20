from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.security import require_api_secret
from app.services.import_service import ContentImportError, import_publish_ready_export

router = APIRouter(prefix="/api/imports", tags=["imports"])


@router.post("/run", dependencies=[Depends(require_api_secret)])
def run_import(db: Session = Depends(get_db)):
    """Ingest Stage 10's flyingfish_publish_ready.json - the only file this backend
    ever reads from the AI pipeline's output. Refuses anything not qa_status='PASS'."""
    path = settings.stage10_export_abs_path
    try:
        result = import_publish_ready_export(db, path)
    except ContentImportError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result
