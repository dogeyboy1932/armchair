from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import storage.postgres_store as pg_store
import storage.neo4j_store    as neo4j
from storage.milvus_store import get_or_create_collection
from api.routes import courses, similarity, graph, ingest


@asynccontextmanager
async def lifespan(app: FastAPI):
    pg_store.init_schema()
    neo4j.init_schema()
    get_or_create_collection()
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
app.include_router(graph.router,      prefix="/graph",      tags=["graph"])
app.include_router(ingest.router,     prefix="/ingest",     tags=["ingest"])


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}
