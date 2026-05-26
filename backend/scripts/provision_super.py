"""配置总后台固定账号密码（无需扫码初始化）"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from super_setup_service import provision_super_account


def main() -> int:
    p = argparse.ArgumentParser(description="Provision super admin account")
    p.add_argument("--username", default=os.environ.get("ADMIN_USER", "cca10"))
    p.add_argument("--password", default=os.environ.get("ADMIN_PASS", ""))
    args = p.parse_args()
    if not args.password:
        print("ERROR: 请通过 --password 或环境变量 ADMIN_PASS 提供密码")
        return 1
    result = provision_super_account(args.username, args.password)
    print(f"OK: 总后台账号 {result['username']} 已配置，initialized={result['initialized']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
