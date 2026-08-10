"""团队语料灌库脚本：读取 assets/knowledge/ 写入 pgvector。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from learning.knowledge import seed_assets  # noqa: E402

if __name__ == "__main__":
    count = seed_assets()
    print(f"seeded {count} chunks")
