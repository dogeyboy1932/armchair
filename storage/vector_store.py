"""
Vector-store dispatcher. Selects backend at import time based on VECTOR_BACKEND:

    VECTOR_BACKEND=milvus     -> storage.milvus_store (local docker-compose stack)
    VECTOR_BACKEND=pgvector   -> storage.pgvector_store (Supabase / any Postgres+pgvector)

Importers should always do:
    from storage import vector_store as vs

and call vs.get_or_create_collection(), vs.insert_chunks(...), etc. — exactly the
same function names as the original milvus_store module.
"""
from __future__ import annotations

import os

_BACKEND = os.environ.get("VECTOR_BACKEND", "milvus").lower().strip()

if _BACKEND == "pgvector":
    from storage.pgvector_store import (  # noqa: F401
        DIM,
        get_or_create_collection,
        insert_chunks,
        get_embeddings_for_course,
        get_chunk_embedding,
        get_chunks_with_embeddings,
        search_in_course,
        search_global_excluding,
        delete_course,
        drop_collection,
    )
elif _BACKEND == "milvus":
    from storage.milvus_store import (  # noqa: F401
        DIM,
        get_or_create_collection,
        insert_chunks,
        get_embeddings_for_course,
        get_chunk_embedding,
        get_chunks_with_embeddings,
        search_in_course,
        search_global_excluding,
        delete_course,
        drop_collection,
    )
else:
    raise ValueError(
        f"VECTOR_BACKEND={_BACKEND!r} is not supported. "
        "Set VECTOR_BACKEND to 'milvus' or 'pgvector'."
    )


BACKEND_NAME = _BACKEND
