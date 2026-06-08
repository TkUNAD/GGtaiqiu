"""将 backend/data/*.json 一次性导入 MySQL app_collections 表"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from db import import_json_files_to_mysql, ping_mysql, storage_info


def main() -> int:
    if not config.USE_MYSQL:
        print("ERROR: 未配置 MySQL（需 MYSQL_HOST / MYSQL_USER / MYSQL_DATABASE）")
        return 1
    print("storage:", storage_info())
    ping = ping_mysql()
    print("ping:", ping)
    if not ping.get("ok"):
        return 1
    result = import_json_files_to_mysql()
    print("import:", result)
    ping2 = ping_mysql()
    print("after:", ping2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
