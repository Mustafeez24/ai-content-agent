from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import calendar, content, dashboard, exports, imports

app = FastAPI(title="FlyingFish Content Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard.router)
app.include_router(content.router)
app.include_router(calendar.router)
app.include_router(exports.router)
app.include_router(imports.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
