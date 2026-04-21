from neo4j import GraphDatabase
import config

_driver = None


def _get_driver():
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(
            config.NEO4J_URI,
            auth=(config.NEO4J_USER, config.NEO4J_PASSWORD),
        )
    return _driver


def init_schema():
    with _get_driver().session() as s:
        s.run(
            "CREATE CONSTRAINT IF NOT EXISTS "
            "FOR (c:Course) REQUIRE c.id IS UNIQUE"
        )


def upsert_course(course_id: str, name: str, description: str = ''):
    with _get_driver().session() as s:
        s.run(
            "MERGE (c:Course {id: $id}) "
            "SET c.name=$name, c.description=$description",
            id=course_id, name=name, description=description,
        )


def upsert_edge(course_a: str, course_b: str, score: float,
                lex_score: float, sem_score: float,
                jsd: float, driving_terms: list):
    with _get_driver().session() as s:
        s.run("""
            MATCH (a:Course {id: $a}), (b:Course {id: $b})
            MERGE (a)-[r:SIMILAR_TO]-(b)
            SET r.score         = $score,
                r.lex_score     = $lex_score,
                r.sem_score     = $sem_score,
                r.jsd           = $jsd,
                r.driving_terms = $driving_terms
        """, a=course_a, b=course_b, score=score,
             lex_score=lex_score, sem_score=sem_score,
             jsd=jsd, driving_terms=driving_terms)


def run_community_detection():
    with _get_driver().session() as s:
        # Drop stale projection if it exists
        try:
            s.run("CALL gds.graph.drop('courseGraph', false)")
        except Exception:
            pass

        s.run("""
            CALL gds.graph.project(
                'courseGraph',
                'Course',
                {
                    SIMILAR_TO: {
                        orientation: 'UNDIRECTED',
                        properties: 'score'
                    }
                }
            )
        """)
        s.run("""
            CALL gds.louvain.write('courseGraph', {
                writeProperty: 'community',
                relationshipWeightProperty: 'score'
            })
        """)
        s.run("""
            CALL gds.pageRank.write('courseGraph', {
                writeProperty: 'pagerank',
                maxIterations: 20,
                relationshipWeightProperty: 'score'
            })
        """)
        s.run("CALL gds.graph.drop('courseGraph')")


def get_shortest_path(from_id: str, to_id: str) -> list:
    with _get_driver().session() as s:
        result = s.run("""
            MATCH p = shortestPath(
                (a:Course {id: $from_id})-[:SIMILAR_TO*]-(b:Course {id: $to_id})
            )
            RETURN
                [n IN nodes(p)         | n.id]    AS ids,
                [n IN nodes(p)         | n.name]  AS names,
                [r IN relationships(p) | r.score] AS scores
        """, from_id=from_id, to_id=to_id)
        record = result.single()
    if not record:
        return []
    ids    = record['ids']
    names  = record['names']
    scores = [None] + record['scores']   # no score on first node
    return [
        {'course_id': ids[i], 'name': names[i], 'edge_score': scores[i]}
        for i in range(len(ids))
    ]


def get_communities() -> dict:
    with _get_driver().session() as s:
        result = s.run("""
            MATCH (c:Course)
            WHERE c.community IS NOT NULL
            RETURN c.community AS community, collect(c.id) AS courses
            ORDER BY community
        """)
        return {int(r['community']): r['courses'] for r in result}


def get_neighbors_graph(course_id: str, top: int = 10) -> list[dict]:
    with _get_driver().session() as s:
        result = s.run("""
            MATCH (a:Course {id: $id})-[r:SIMILAR_TO]-(b:Course)
            RETURN b.id   AS course_id,
                   b.name AS name,
                   r.score         AS score,
                   r.lex_score     AS lex_score,
                   r.sem_score     AS sem_score,
                   r.driving_terms AS driving_terms
            ORDER BY r.score DESC
            LIMIT $top
        """, id=course_id, top=top)
        return [dict(r) for r in result]


def get_full_graph(min_score: float = 0.4) -> dict:
    """Return all nodes and edges for graph visualisation."""
    with _get_driver().session() as s:
        nodes_result = s.run("""
            MATCH (c:Course)
            RETURN c.id AS id, c.name AS name,
                   coalesce(c.community, 0)  AS community,
                   coalesce(c.pagerank, 0.0) AS pagerank
        """)
        nodes = [dict(r) for r in nodes_result]

        edges_result = s.run("""
            MATCH (a:Course)-[r:SIMILAR_TO]->(b:Course)
            WHERE r.score >= $min_score
            RETURN a.id AS source, b.id AS target,
                   r.score         AS score,
                   r.lex_score     AS lex_score,
                   r.sem_score     AS sem_score,
                   r.driving_terms AS driving_terms
        """, min_score=min_score)
        edges = [dict(r) for r in edges_result]

    return {"nodes": nodes, "edges": edges}


def clear():
    with _get_driver().session() as s:
        s.run("MATCH (n) DETACH DELETE n")
