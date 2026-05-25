from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import storage.postgres_store as pg_store
import storage.neo4j_store    as neo4j
from storage import vector_store as vs
from api.routes import courses, similarity, graph, ingest, topics

PUBLIC_DIR = Path(__file__).parent.parent / "public"


@asynccontextmanager
async def lifespan(app: FastAPI):
    pg_store.init_schema()
    neo4j.init_schema()
    vs.get_or_create_collection()
    yield


app = FastAPI(
    title="SIIP Semantic Similarity API",
    description=(
        "Hybrid IR + vector course-similarity engine. "
        "Uses Dirichlet-smoothed JSD (lexical) + SciNCL cosine similarity (semantic)."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(courses.router,    prefix="/courses",    tags=["courses"])
app.include_router(similarity.router, prefix="/similarity", tags=["similarity"])
app.include_router(topics.router,     prefix="/topics",     tags=["topics"])
app.include_router(graph.router,      prefix="/graph",      tags=["graph"])
app.include_router(ingest.router,     prefix="/ingest",     tags=["ingest"])

app.mount("/static", StaticFiles(directory=str(PUBLIC_DIR)), name="static")


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def ui():
    return FileResponse(
        PUBLIC_DIR / "index.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"},
    )


@app.get("/upload", include_in_schema=False)
def upload_page():
    return FileResponse(PUBLIC_DIR / "upload.html")
