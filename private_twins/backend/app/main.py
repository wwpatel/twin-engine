from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import allowed_origins
from app.routes.health import router as health_router
from app.routes.me import router as me_router
from app.routes.runs import router as runs_router
from app.routes.twins import router as twins_router

app = FastAPI(title="Twin Engine", version="0.1.0")
origins = allowed_origins()
if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

app.include_router(health_router)
app.include_router(me_router)
app.include_router(runs_router)
app.include_router(twins_router)
