from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.routes import router as api_router
from app.api.ws import router as ws_router
from app.db.engine import SessionLocal
from app.settings import get_settings


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


settings = get_settings()
app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health(db: Session = Depends(get_db)):
    _ = db.execute(text("SELECT 1"))
    return {"status": "ok"}


app.include_router(api_router)
app.include_router(ws_router)
