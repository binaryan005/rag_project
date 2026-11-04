from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import init_db
from app.routes.documents import router as documents_router
from app.routes.analysis import router as analysis_router
from app.routes.web_search import router as web_search_router
from app.services.cuad_service import cuad_service

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    init_db()
    print("Pre-loading CUAD RoBERTa model...")
    cuad_service._initialize()
    yield
    # Shutdown logic

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Legal Document RAG Ingestion & Vector Search Backend",
    lifespan=lifespan
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(documents_router, prefix=settings.API_PREFIX)
app.include_router(analysis_router, prefix=settings.API_PREFIX)
app.include_router(web_search_router, prefix=settings.API_PREFIX)

@app.get("/", tags=["Health"])
def root():
    return {
        "status": "online",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION
    }

@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "ok"}
