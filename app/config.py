"""全局配置：路径、模型参数、安全提示文案。"""
import os
from pathlib import Path

from dotenv import load_dotenv

# 项目根目录（app/ 的上一级）
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# ---------- 路径 ----------
DATA_DIR = BASE_DIR / "data"
PDF_DIR = DATA_DIR / "pdfs"
TEXT_DIR = DATA_DIR / "texts"
INTERACTIONS_CSV = DATA_DIR / "interactions.csv"
TEST_SET_PATH = DATA_DIR / "test_set.json"
# 向量库必须落在纯 ASCII 路径：chroma-hnswlib(C++) 写 HNSW .bin 时无法处理中文路径
CHROMA_DIR = Path("D:/chroma_db")
OUTPUT_DIR = BASE_DIR / "outputs"
LOG_FILE = OUTPUT_DIR / "run.log"
FEEDBACK_FILE = OUTPUT_DIR / "feedback.jsonl"
EVAL_REPORT = OUTPUT_DIR / "eval_report.json"

# ---------- 检索 ----------
# 嵌入模型：优先使用本地 models/bge-small-zh-v1.5（离线可用），否则走远程 BAAI/bge-small-zh-v1.5
LOCAL_EMBED_DIR = BASE_DIR / "models" / "bge-small-zh-v1.5"
_embed_env = os.getenv("EMBEDDING_MODEL", "")
if _embed_env and Path(_embed_env).is_dir():
    EMBEDDING_MODEL = _embed_env
elif (LOCAL_EMBED_DIR / "config.json").exists():
    EMBEDDING_MODEL = str(LOCAL_EMBED_DIR)
else:
    EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
COLLECTION_NAME = "drug_instructions"
TOP_K = int(os.getenv("TOP_K", "12"))
# 分块：单个分块最大字符数，超长章节按句切分
CHUNK_MAX_CHARS = 500

# ---------- 大模型（OpenAI 兼容接口，国内大模型） ----------
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))

# 是否在线模式：有 API Key 走大模型，否则走确定性离线模板（演示/评测）
ONLINE_MODE = bool(LLM_API_KEY)

# ---------- 多轮对话 ----------
HISTORY_TURNS = int(os.getenv("HISTORY_TURNS", "3"))
# 列出全部治疗方案需要更长的回答空间
MAX_TOKENS = 2048

# ---------- 安全文案 ----------
EMERGENCY_RESPONSE = (
    "⚠️ 【紧急提醒】\n"
    "检测到您的问题可能涉及危及生命的急症情况。"
    "请立即拨打 **120 急救电话** 或前往最近医院的急诊科，不要等待！\n"
    "在等待救援期间：保持患者平卧、保持呼吸道通畅，切勿自行喂药或喂水。"
)
DISCLAIMER = "\n\n---\n*免责声明：以上内容仅供学习参考，不构成医疗建议。用药请遵医嘱，如有不适请及时就医。*"

# ---------- LangSmith（可选） ----------
LANGSMITH_TRACING = os.getenv("LANGSMITH_TRACING", "false").lower() == "true"
