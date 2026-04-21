from fastapi import APIRouter, HTTPException, Query
import storage.neo4j_store as neo4j

router = APIRouter()


@router.get("/path")
def shortest_path(
    from_course: str = Query(..., alias="from", description="Start course ID"),
    to_course:   str = Query(..., alias="to",   description="End course ID"),
):
    """
    Shortest conceptual path between two courses in the Neo4j similarity graph.
    Each hop is a SIMILAR_TO edge; edge_score shows how similar adjacent courses are.
    """
    path = neo4j.get_shortest_path(from_course, to_course)
    if not path:
        raise HTTPException(
            404,
            detail=f"No path found between '{from_course}' and '{to_course}'",
        )
    return {"from": from_course, "to": to_course, "path": path}


@router.get("/communities")
def get_communities():
    """
    Louvain community assignments. Each key is a community ID;
    value is the list of course IDs in that community.
    Run scripts/build_graph.py to populate.
    """
    communities = neo4j.get_communities()
    if not communities:
        raise HTTPException(
            404,
            detail="No communities found. Run scripts/build_graph.py first.",
        )
    return communities


@router.get("/neighbors")
def graph_neighbors(
    course: str = Query(..., description="Course ID"),
    top:    int  = Query(10, ge=1, le=50),
):
    """Neighbours from the Neo4j graph (includes name + driving_terms)."""
    neighbors = neo4j.get_neighbors_graph(course, top)
    if not neighbors:
        raise HTTPException(404, detail=f"No graph neighbours for '{course}'")
    return {"course": course, "neighbors": neighbors}
