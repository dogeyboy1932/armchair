import numpy as np
from pymilvus import (
    connections, Collection, CollectionSchema,
    FieldSchema, DataType, utility,
)
import config

COLLECTION = "siip_chunks"
DIM        = 768


def _connect():
    connections.connect("default", host=config.MILVUS_HOST, port=config.MILVUS_PORT)


def get_or_create_collection() -> Collection:
    _connect()
    if utility.has_collection(COLLECTION):
        col = Collection(COLLECTION)
        col.load()
        return col

    fields = [
        FieldSchema("id",        DataType.INT64,        is_primary=True, auto_id=True),
        FieldSchema("chunk_id",  DataType.VARCHAR,      max_length=512),
        FieldSchema("course_id", DataType.VARCHAR,      max_length=64),
        FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=DIM),
    ]
    schema = CollectionSchema(fields, description="Course concept chunks")
    col    = Collection(COLLECTION, schema=schema)
    col.create_index(
        "embedding",
        {"metric_type": "COSINE", "index_type": "FLAT", "params": {}},
    )
    col.load()
    return col


def insert_chunks(chunks: list[dict]):
    """chunks: list of {chunk_id, course_id, embedding (np.ndarray shape (768,))}"""
    if not chunks:
        return
    col = get_or_create_collection()
    col.insert([
        [c["chunk_id"]           for c in chunks],
        [c["course_id"]          for c in chunks],
        [c["embedding"].tolist() for c in chunks],
    ])
    col.flush()


def get_embeddings_for_course(course_id: str) -> list[np.ndarray]:
    col = get_or_create_collection()
    results = col.query(
        expr=f'course_id == "{course_id}"',
        output_fields=["embedding"],
    )
    return [np.array(r["embedding"], dtype=np.float32) for r in results]


def search_in_course(
    query_vectors: list[np.ndarray],
    course_id: str,
    limit: int = 1,
) -> list[float]:
    """
    For each query vector return the best cosine similarity score
    against the chunks belonging to course_id.
    Returns a list of floats (one per query vector).
    """
    col = get_or_create_collection()
    if not query_vectors:
        return []

    results = col.search(
        data=[v.tolist() for v in query_vectors],
        anns_field="embedding",
        param={"metric_type": "COSINE", "params": {}},
        limit=limit,
        expr=f'course_id == "{course_id}"',
        output_fields=["chunk_id"],
    )

    scores = []
    for hits in results:
        scores.append(float(hits[0].score) if hits else 0.0)
    return scores


def delete_course(course_id: str):
    col = get_or_create_collection()
    col.delete(expr=f'course_id == "{course_id}"')
    col.flush()


def drop_collection():
    _connect()
    if utility.has_collection(COLLECTION):
        utility.drop_collection(COLLECTION)
