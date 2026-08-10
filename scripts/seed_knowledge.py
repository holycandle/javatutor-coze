"""团队语料灌库脚本：读取 assets/knowledge/ 写入 pgvector。

用法:
  uv run python scripts/seed_knowledge.py            # 全量灌库（同 source 自动去重）
  uv run python scripts/seed_knowledge.py --stats     # 查看当前知识库统计
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()


def show_stats():
    """打印当前知识库的统计信息。"""
    import psycopg
    from storage.database.db import get_db_url

    url = get_db_url()
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM knowledge_chunks")
            total = cur.fetchone()[0]
            cur.execute(
                "SELECT source, count(*) FROM knowledge_chunks "
                "GROUP BY source ORDER BY source"
            )
            rows = cur.fetchall()
    print(f"知识库总计: {total} 条分块")
    for source, cnt in rows:
        print(f"  {source}: {cnt} 条")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RAG 知识库灌库脚本")
    parser.add_argument("--stats", action="store_true", help="仅查看统计，不灌库")
    args = parser.parse_args()

    if args.stats:
        show_stats()
        sys.exit(0)

    from learning.knowledge import seed_assets

    count = seed_assets()
    print(f"灌库完成: {count} 条分块已写入 knowledge_chunks 表")
    print()
    show_stats()
