"""从 ORM 模型离线生成 PostgreSQL DDL（schema.sql）。

无需连接数据库：仅用 postgresql 方言把 Base.metadata 编译成 CREATE TABLE 文本。
表结构唯一事实源是 app/models/，本脚本只是导出产物，勿手改 schema.sql。

用法：
    cd dev/service
    python scripts/dump_schema.py [输出路径，默认 dev/service/schema.sql]
"""
import sys
from pathlib import Path

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable, CreateIndex

# 让 `python scripts/dump_schema.py` 从任意目录运行时都能 import 到 app 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 注册所有模型到 Base.metadata（必须 import 全量，漏了表就不会出现在 DDL）
from app.core.database import Base  # noqa: E402
from app.models import *  # noqa: F401,F403,E402


def generate_ddl() -> str:
    dialect = postgresql.dialect()
    statements = []
    # sorted_tables 按外键依赖排序：先父表后子表，保证 CREATE 顺序正确
    for table in Base.metadata.sorted_tables:
        sql = str(CreateTable(table).compile(dialect=dialect))
        statements.append(sql.rstrip() + ";")
        # 列级 index=True 不会进 CREATE TABLE，需单独渲染 CREATE INDEX
        for index in table.indexes:
            statements.append(str(CreateIndex(index).compile(dialect=dialect)).rstrip() + ";")
    header = (
        "-- schema.sql\n"
        "-- 由 scripts/dump_schema.py 从 ORM (app/models) 自动生成，请勿手工编辑。\n"
        "-- 导入：psql -U <user> -d <db> -f schema.sql\n"
    )
    return header + "\n\n".join(statements) + "\n"


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "schema.sql"
    ddl = generate_ddl()
    out.write_text(ddl, encoding="utf-8")
    print(f"written: {out}  ({len(Base.metadata.tables)} tables)")


if __name__ == "__main__":
    main()
