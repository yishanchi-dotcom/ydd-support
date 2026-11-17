# -*- coding: utf-8 -*-
"""
资料库升级 / 检查工具（可单独执行，不需启动服务）。

用法：
  python migrate.py            检查版本并套用所有未执行的升级（会先自动备份）
  python migrate.py --status   只显示目前版本，不做任何修改
  python migrate.py --backup   立即手动备份一份资料库
  python migrate.py --db 路径   指定资料库档案（预设读取 config.json 的 db_path）
"""
import sys
import json
import os

import db

HERE = os.path.dirname(os.path.abspath(__file__))


def db_path_from_args():
    if "--db" in sys.argv:
        return sys.argv[sys.argv.index("--db") + 1]
    cfg = os.path.join(HERE, "config.json")
    if os.path.exists(cfg):
        with open(cfg, encoding="utf-8") as f:
            p = json.load(f).get("db_path")
            if p:
                return p if os.path.isabs(p) else os.path.join(HERE, p)
    return os.path.join(HERE, "data", "support.db")


def main():
    path = db_path_from_args()
    print("资料库：%s" % path)
    if "--status" in sys.argv:
        s = db.status(path)
        if not s["exists"]:
            print("资料库尚未建立（首次启动服务时会自动建立）。")
            return
        print("目前版本：v%d　程式支援最新版本：v%d" % (s["version"], s["latest"]))
        for a in s["applied"]:
            print("  v%(version)d  %(applied_at)s  %(name)s" % a)
        if s["version"] < s["latest"]:
            print("→ 有待套用的升级，请执行：python migrate.py")
        return
    if "--backup" in sys.argv:
        print("已备份：%s" % db.backup(path, tag="manual"))
        return
    before, after = db.migrate(path)
    if before == after:
        print("资料库已是最新版本 v%d，无需升级。" % after)
    else:
        print("升级完成：v%d → v%d" % (before, after))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("❌ 失败：%s" % e)
        sys.exit(1)
