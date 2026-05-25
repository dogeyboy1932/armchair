import os
from pathlib import Path
from urllib.parse import urlparse, unquote
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / '.env')


def _parse_database_url(url: str) -> dict | None:
    """Parse a postgres:// connection URL into individual fields."""
    if not url:
        return None
    p = urlparse(url)
    if p.scheme not in ('postgres', 'postgresql'):
        return None
    return {
        'host':     p.hostname or 'localhost',
        'port':     p.port or 5432,
        'db':       (p.path or '/').lstrip('/') or 'postgres',
        'user':     unquote(p.username) if p.username else '',
        'password': unquote(p.password) if p.password else '',
        'sslmode':  'require' if 'sslmode=require' in (p.query or '') else None,
    }


_pg_url = _parse_database_url(os.environ.get('DATABASE_URL', ''))

# PostgreSQL (DATABASE_URL takes priority over individual vars)
POSTGRES_HOST     = (_pg_url or {}).get('host')     or os.environ.get('POSTGRES_HOST', 'localhost')
POSTGRES_PORT     = (_pg_url or {}).get('port')     or int(os.environ.get('POSTGRES_PORT', 5432))
POSTGRES_DB       = (_pg_url or {}).get('db')       or os.environ.get('POSTGRES_DB', 'siip')
POSTGRES_USER     = (_pg_url or {}).get('user')     or os.environ.get('POSTGRES_USER', 'siip')
POSTGRES_PASSWORD = (_pg_url or {}).get('password') or os.environ.get('POSTGRES_PASSWORD', '')
POSTGRES_SSLMODE  = (_pg_url or {}).get('sslmode')  or os.environ.get('POSTGRES_SSLMODE')

# Vector backend: 'milvus' (local docker stack) or 'pgvector' (managed Postgres)
VECTOR_BACKEND = os.environ.get('VECTOR_BACKEND', 'milvus').lower().strip()

# Milvus (only used when VECTOR_BACKEND=milvus)
MILVUS_HOST = os.environ.get('MILVUS_HOST', 'localhost')
MILVUS_PORT = int(os.environ.get('MILVUS_PORT', 19530))

# Neo4j
NEO4J_URI      = os.environ.get('NEO4J_URI', 'bolt://localhost:7687')
NEO4J_USER     = os.environ.get('NEO4J_USER', 'neo4j')
NEO4J_PASSWORD = os.environ.get('NEO4J_PASSWORD', '')

# Scoring
# Hybrid = (ALPHA_LEX·lex + ALPHA_SEM·sem + ALPHA_CAT·(1-category_jsd)) / sum(weights)
# Weights are auto-normalized so they don't have to sum to 1.
# When category_jsd is unavailable, ALPHA_CAT weight is split proportionally between lex and sem.
ALPHA_LEX           = float(os.environ.get('ALPHA_LEX', 0.3))
ALPHA_SEM           = float(os.environ.get('ALPHA_SEM', 0.5))
ALPHA_CAT           = float(os.environ.get('ALPHA_CAT', 0.2))
ALPHA               = float(os.environ.get('ALPHA', 0.4))     # legacy fallback, unused when ALPHA_LEX/SEM/CAT set
DIRICHLET_MU        = float(os.environ.get('DIRICHLET_MU', 2000.0))
MIN_SCORE           = float(os.environ.get('MIN_SCORE', 0.55))
TOP_K_MILVUS        = int(os.environ.get('TOP_K_MILVUS', 5))
TOP_K_DRIVING_TERMS = int(os.environ.get('TOP_K_DRIVING_TERMS', 8))

# Model
SCINCL_MODEL     = os.environ.get('SCINCL_MODEL', 'malteos/scincl')
SCINCL_CACHE_DIR = os.environ.get('SCINCL_CACHE_DIR', str(Path(__file__).parent / '.model_cache'))

# Data paths
DATA_DIR         = Path(__file__).parent / 'data'
SYLLABI_PATH     = DATA_DIR / 'mechse_syllabi.json'
DEFINITIONS_PATH = DATA_DIR / 'topic_definitions.json'
COURSE_INFO_PATH = DATA_DIR / 'course_info.json'
INSTRUCTORS_PATH = DATA_DIR / 'instructors.json'

# LLM (Gemini API)
GEMINI_API_KEY       = os.environ.get('GEMINI_API_KEY', '')
CATEGORY_LABEL_MODEL = os.environ.get('CATEGORY_LABEL_MODEL', 'gemini-2.0-flash-lite')
LLM_EXPLAIN_MODEL    = os.environ.get('LLM_EXPLAIN_MODEL', 'gemini-2.0-flash')
NON_OBVIOUS_TOP_K    = int(os.environ.get('NON_OBVIOUS_TOP_K', 50))
