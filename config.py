import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / '.env')

# PostgreSQL
POSTGRES_HOST     = os.environ.get('POSTGRES_HOST', 'localhost')
POSTGRES_PORT     = int(os.environ.get('POSTGRES_PORT', 5432))
POSTGRES_DB       = os.environ.get('POSTGRES_DB', 'siip')
POSTGRES_USER     = os.environ.get('POSTGRES_USER', 'siip')
POSTGRES_PASSWORD = os.environ.get('POSTGRES_PASSWORD', '')

# Milvus
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
