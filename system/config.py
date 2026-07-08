"""
系统配置中心
"""
import os
import re

# 加载 .env 文件（优先级低于系统环境变量）
from dotenv import load_dotenv
import logging
logger = logging.getLogger(__name__)

_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.isfile(_env_path):
    load_dotenv(_env_path)
    logger.info("已加载 .env 配置文件")
else:
    logger.debug("未找到 .env 文件，跳过（可手动 export 环境变量）")

# 项目根目录
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 数据目录
DATA_DIR = os.path.join(ROOT_DIR, "data")
TRAINING_DATA_DIR = os.path.join(ROOT_DIR, "data", "training")
MODEL_DIR = os.path.join(ROOT_DIR, "models")
UPLOAD_DIR = os.path.join(ROOT_DIR, "data", "uploads")

# 模型路径
INTENT_MODEL_PATH = os.path.join(MODEL_DIR, "intent_model")
EMBEDDING_MODEL_PATH = os.path.join(MODEL_DIR, "embedding_model")

# DeepSeek API
def get_api_key() -> str:
    """运行时读取环境变量，避免模块导入时缓存旧值"""
    return os.environ.get("DEEPSEEK_API_KEY", "")

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# 训练默认参数
INTENT_TRAIN_CONFIG = {
    "model_name": "bert-base-chinese",
    "max_length": 64,
    "batch_size": 32,
    "epochs": 10,
    "learning_rate": 2e-5,
}

EMBEDDING_TRAIN_CONFIG = {
    "model_name": "BAAI/bge-small-zh-v1.5",
    "max_length": 256,
    "batch_size": 8,
    "epochs": 3,
    "learning_rate": 2e-5,
    "temperature": 0.05,
    "max_train_chunks": 200,   # 训练用最大段落数（超出则随机采样），避免大文档库训练过慢
}

# 确保目录存在
for d in [DATA_DIR, TRAINING_DATA_DIR, MODEL_DIR, UPLOAD_DIR]:
    os.makedirs(d, exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "configs"), exist_ok=True)

# 便捷常量
CONFIGS_DIR = os.path.join(DATA_DIR, "configs")
CHROMA_DB_DIR = os.path.join(ROOT_DIR, "chroma_db")


def scan_upload_documents(base_dir: str = None) -> list:
    """
    扫描上传目录，支持按领域子文件夹组织。

    目录结构示例：
      data/uploads/
        ├── 产品/
        │   ├── 产品手册.txt
        │   └── 规格参数.txt
        ├── 销售/
        │   └── 销售政策.md
        ├── 售后/
        │   └── 保修条款.txt
        └── 通用文档.txt          ← 无子文件夹 = 通用领域

    返回: [{"filename": "产品/产品手册.txt", "domain": "产品", "path": "..."}, ...]
    """
    if base_dir is None:
        base_dir = UPLOAD_DIR

    result = []
    if not os.path.isdir(base_dir):
        return result

    for entry in sorted(os.listdir(base_dir)):
        full = os.path.join(base_dir, entry)
        if os.path.isdir(full):
            # 子文件夹 = 一个领域
            domain = entry
            for fname in sorted(os.listdir(full)):
                fpath = os.path.join(full, fname)
                if os.path.isfile(fpath):
                    result.append({
                        "filename": f"{domain}/{fname}",
                        "domain": domain,
                        "path": fpath,
                    })
        elif os.path.isfile(full):
            # 根目录下的文件 = 通用领域
            result.append({
                "filename": entry,
                "domain": "通用",
                "path": full,
            })

    return result


def split_document_chunks(content: str) -> list:
    """
    按段落切分文档，自动过滤无意义的章节分隔符和纯装饰行。

    过滤规则：
      1. 去掉由 = - * # ~ 等装饰字符主导的行（占比 > 50%）
      2. 去掉去除装饰行后有效内容 < 15 字符的段落
      3. 去掉中文/字母数字字符 < 10 个的段落
    """
    raw_chunks = [p.strip() for p in content.split("\n\n") if p.strip()]

    clean = []
    for chunk in raw_chunks:
        # ---- 逐行过滤装饰线 ----
        lines = chunk.split("\n")
        meaningful_lines = []
        for line in lines:
            s = line.strip()
            if not s:
                continue
            # 检查是否为装饰字符主导的行（如 ========, --------, ********）
            is_decorative = False
            for ch in "=-*#~_":
                if len(s) >= 5 and s.count(ch) / len(s) > 0.5:
                    is_decorative = True
                    break
            if not is_decorative:
                meaningful_lines.append(line)

        clean_text = "\n".join(meaningful_lines).strip()
        if not clean_text:
            continue

        # ---- 最小内容长度 ----
        if len(clean_text) < 15:
            continue

        # ---- 必须包含足够的实际文字（中文或字母数字）----
        text_chars = re.findall(r"[一-鿿\w]", clean_text)
        if len(text_chars) < 10:
            continue

        clean.append(clean_text)

    return clean
