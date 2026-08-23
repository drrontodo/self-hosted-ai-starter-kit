from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import config, db, news, scheduler
from .routes import api, dashboard


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    news.seed_default_feeds()
    if config.SCHEDULER_ENABLED:
        scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="CPD Companion", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(api.router)
app.include_router(dashboard.router)
app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "static")), name="static")


@app.get("/health")
def health():
    return {"status": "ok"}
