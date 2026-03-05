import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from routers import auth, proposals, generation

app = FastAPI(title="Pahle India Research Proposal API", version="1.0.0")

cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in cors_origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(proposals.router, prefix="/api/v1/proposals", tags=["proposals"])
app.include_router(generation.router, prefix="/api/v1/generation", tags=["generation"])


@app.get("/health")
def health():
    return {"status": "ok"}
