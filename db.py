# -*- coding: utf-8 -*-
"""
资料库结构与版本迁移。

规则（上线后必须遵守，确保向下兼容）：
1. 已发布的迁移步骤永远不能修改或删除，只能在 MIGRATIONS 末尾追加新版本。
2. 新版本只做「加法」：新增资料表、新增栏位（必须给预设值）、新增索引、修正资料。
   不删除、不改名已有栏位；旧栏位若不再使用就保留不动。
3. 每次升级前自动备份资料库到 backups/ 资料夹，升级失败会整批回滚。
4. 伺服器启动时会自动套用尚未执行的迁移；也可用 migrate.py 单独执行与检查。
"""
import os
import sqlite3
import time
import datetime

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS accounts(
  code TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'store',      -- store / hr
  phone TEXT NOT NULL DEFAULT '',          -- 门店联系电话（仅资料，不作登录用）
  active INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER, updated_at INTEGER
);
CREATE TABLE IF NOT EXISTS staff(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  store TEXT NOT NULL,
  name TEXT NOT NULL,
  emp_no TEXT NOT NULL DEFAULT '',
  active INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER, updated_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_staff_store ON staff(store);
CREATE INDEX IF NOT EXISTS idx_staff_empno ON staff(emp_no);

CREATE TABLE IF NOT EXISTS requests(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  month TEXT NOT NULL, date TEXT NOT NULL,
  start_time TEXT NOT NULL, end_time TEXT NOT NULL, hours REAL NOT NULL,
  from_store TEXT NOT NULL, to_store TEXT NOT NULL,
  from_name TEXT, to_name TEXT,
  staff_id INTEGER, staff_name TEXT, staff_emp_no TEXT DEFAULT '',
  initiator TEXT NOT NULL, counterparty TEXT NOT NULL, kind TEXT,   -- kind: out(调出) / in(调入)
  reason TEXT DEFAULT '', note TEXT DEFAULT '',
  status TEXT NOT NULL,      -- pending / approved / rejected / withdrawn / disputed / cancelled
  dispute_by TEXT, dispute_note TEXT, dispute_at INTEGER,
  created_at INTEGER, decided_at INTEGER, updated_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_req_month ON requests(month);
CREATE INDEX IF NOT EXISTS idx_req_status ON requests(status);
CREATE INDEX IF NOT EXISTS idx_req_cp ON requests(counterparty, status);
CREATE INDEX IF NOT EXISTS idx_req_init ON requests(initiator, status);
CREATE INDEX IF NOT EXISTS idx_req_staff ON requests(staff_id, date);

CREATE TABLE IF NOT EXISTS request_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id INTEGER NOT NULL, t INTEGER, who TEXT, act TEXT, note TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_evt_req ON request_events(request_id);

CREATE TABLE IF NOT EXISTS confirms(
  month TEXT NOT NULL, store TEXT NOT NULL,
  manager TEXT, signature TEXT, signed_at INTEGER,
  sig TEXT, count INTEGER, out_hours REAL, in_hours REAL,
  PRIMARY KEY(month, store)
);

CREATE TABLE IF NOT EXISTS sessions(
  token TEXT PRIMARY KEY, code TEXT NOT NULL,
  created_at INTEGER, last_seen INTEGER, ip TEXT, device TEXT
);
CREATE INDEX IF NOT EXISTS idx_sess_code ON sessions(code);

CREATE TABLE IF NOT EXISTS logs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  t INTEGER NOT NULL, code TEXT, role TEXT, action TEXT, detail TEXT,
  ip TEXT, device TEXT, ua TEXT
);
CREATE INDEX IF NOT EXISTS idx_logs_t ON logs(t);
CREATE INDEX IF NOT EXISTS idx_logs_code ON logs(code);

CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
"""

# v3 预置的 2027 年法定节假日（三倍薪日，依《全国年节及纪念日放假办法》与国办发明电〔2026〕10号）
HOLIDAYS_2027 = [
    ("2027-01-01", "元旦"), ("2027-02-05", "春节（除夕）"), ("2027-02-06", "春节（初一）"), ("2027-02-07", "春节（初二）"),
    ("2027-02-08", "春节（初三）"), ("2027-04-05", "清明节"), ("2027-05-01", "劳动节"), ("2027-05-02", "劳动节"),
    ("2027-06-09", "端午节"), ("2027-09-15", "中秋节"), ("2027-10-01", "国庆节"), ("2027-10-02", "国庆节"), ("2027-10-03", "国庆节"),
]
SETTING_DEFAULTS = {
    "night_pay": "10", "long_pay": "10", "night_start": "22:00", "long_km": "20",
    "prep_min": "60", "clean_min": "30", "amap_key": "", "amap_sec": "",
    "hq_lunch_start": "12:00", "hq_lunch_end": "13:00",
}
# v4 新增的设定（不改动 v3 已发布的预设）
SETTING_DEFAULTS_V4 = {"amap_ws_key": "", "dist_mode": "driving"}


def _migrate_v3(conn):
    stmts = [
        "ALTER TABLE accounts ADD COLUMN address TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE accounts ADD COLUMN lat REAL DEFAULT NULL",
        "ALTER TABLE accounts ADD COLUMN lng REAL DEFAULT NULL",
        """CREATE TABLE IF NOT EXISTS store_hours(
             id INTEGER PRIMARY KEY AUTOINCREMENT, store TEXT NOT NULL,
             days TEXT NOT NULL DEFAULT '',          -- '' = 每天；否则 0=周日…6=周六、7=法定节假日，逗号分隔
             open_time TEXT NOT NULL, close_time TEXT NOT NULL,   -- close 可超过 24:00（次日）
             sort INTEGER NOT NULL DEFAULT 0)""",
        "CREATE INDEX IF NOT EXISTS idx_hours_store ON store_hours(store)",
        "CREATE TABLE IF NOT EXISTS holidays(date TEXT PRIMARY KEY, name TEXT NOT NULL)",
        "ALTER TABLE requests ADD COLUMN nature TEXT NOT NULL DEFAULT 'op'",      # op 营运 / non 非营运
        "ALTER TABLE requests ADD COLUMN special TEXT NOT NULL DEFAULT ''",       # 特殊状况 / 非营运项目
        "ALTER TABLE requests ADD COLUMN holiday TEXT NOT NULL DEFAULT ''",       # 三倍薪日名称
        "ALTER TABLE requests ADD COLUMN op_hours REAL DEFAULT NULL",
        "ALTER TABLE requests ADD COLUMN non_hours REAL NOT NULL DEFAULT 0",
        "ALTER TABLE requests ADD COLUMN night_hours REAL NOT NULL DEFAULT 0",
        "ALTER TABLE requests ADD COLUMN night_pay REAL NOT NULL DEFAULT 0",
        "ALTER TABLE requests ADD COLUMN long_km REAL DEFAULT NULL",
        "ALTER TABLE requests ADD COLUMN long_pay REAL NOT NULL DEFAULT 0",
        "ALTER TABLE requests ADD COLUMN out_of_hours INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE requests ADD COLUMN payer TEXT DEFAULT NULL",
        "ALTER TABLE requests ADD COLUMN adj_nature TEXT DEFAULT NULL",
        "ALTER TABLE requests ADD COLUMN adj_special TEXT DEFAULT NULL",
    ]
    for st in stmts:
        conn.execute(st)
    # 旧记录：一律视为营运支援、非节假日
    conn.execute("UPDATE requests SET op_hours = hours, payer = to_store WHERE op_hours IS NULL")
    for d, n in HOLIDAYS_2027:
        conn.execute("INSERT OR IGNORE INTO holidays(date, name) VALUES(?,?)", (d, n))
    for k, v in SETTING_DEFAULTS.items():
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?,?)", (k, v))


def _migrate_v4(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS store_distances(
        a TEXT NOT NULL, b TEXT NOT NULL,           -- 门店编号，a < b
        km REAL NOT NULL, source TEXT NOT NULL,      -- driving 驾车 / straight 直线
        updated_at INTEGER, PRIMARY KEY(a, b))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS long_overrides(
        a TEXT NOT NULL, b TEXT NOT NULL,           -- 门店编号，a < b
        is_long INTEGER NOT NULL,                    -- 人资指定：1 长途 / 0 非长途
        updated_by TEXT, updated_at INTEGER, PRIMARY KEY(a, b))""")
    for k, v in SETTING_DEFAULTS_V4.items():
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?,?)", (k, v))


def _exec_many(conn, sql):
    """逐句执行（executescript 会自动 COMMIT，破坏迁移交易）。"""
    import re as _re
    sql = _re.sub(r"--[^\n]*", "", sql)
    for st in sql.split(";"):
        if st.strip():
            conn.execute(st)


ASSET_SETTING_DEFAULTS = {
    "asset_no_prefix": "TJ",          # 资产编号前缀（示例规则：前缀-品项代码-年份-4 位流水号）
    "oss_region": "oss-cn-beijing", "oss_bucket": "", "oss_ak_id": "", "oss_ak_secret": "",
    "ai_key": "", "ai_model": "qwen-vl-plus",
    "stockin_overdue_days": "3",
}


def _migrate_v5(conn):
    _exec_many(conn, """
    CREATE TABLE IF NOT EXISTS asset_items(
        id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, code TEXT NOT NULL DEFAULT '',
        price REAL NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1, created_at INTEGER);
    CREATE TABLE IF NOT EXISTS assets(
        id INTEGER PRIMARY KEY, asset_no TEXT NOT NULL UNIQUE, item_id INTEGER, name TEXT NOT NULL,
        store TEXT, buy_date TEXT DEFAULT '', price REAL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'active',      -- pending_in 待入库 / active 在用 / transit 调拨中 / scrapped 已报废 / lost 盘亏
        cond TEXT NOT NULL DEFAULT '正常',          -- 正常 / 闲置 / 损坏待修
        note TEXT DEFAULT '', purchase_id INTEGER, label_printed INTEGER DEFAULT 0, import_batch TEXT DEFAULT '',
        created_at INTEGER, updated_at INTEGER);
    CREATE INDEX IF NOT EXISTS idx_assets_store ON assets(store, status);
    CREATE TABLE IF NOT EXISTS asset_events(
        id INTEGER PRIMARY KEY, asset_id INTEGER NOT NULL, t INTEGER, who TEXT, kind TEXT, detail TEXT DEFAULT '', photos TEXT DEFAULT '');
    CREATE INDEX IF NOT EXISTS idx_asset_events ON asset_events(asset_id);
    CREATE TABLE IF NOT EXISTS asset_photos(
        id INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE, store TEXT, asset_no TEXT, ctx TEXT, sha TEXT, size INTEGER,
        location TEXT NOT NULL DEFAULT 'local', ai TEXT DEFAULT '', created_by TEXT, created_at INTEGER);
    CREATE INDEX IF NOT EXISTS idx_photo_sha ON asset_photos(sha);
    CREATE TABLE IF NOT EXISTS asset_moves(
        id INTEGER PRIMARY KEY, kind TEXT NOT NULL,     -- transfer 调拨 / scrap 报废 / stockin 购入入库
        asset_id INTEGER NOT NULL, from_store TEXT DEFAULT '', to_store TEXT DEFAULT '',
        status TEXT NOT NULL,                          -- pending 待审批 / approved 待出库 / shipped 待收货(入库) / done / rejected / cancelled / refused 拒收
        reason TEXT DEFAULT '', note TEXT DEFAULT '', photos TEXT DEFAULT '', created_by TEXT, created_at INTEGER,
        decided_by TEXT DEFAULT '', decided_at INTEGER, decide_note TEXT DEFAULT '',
        ship_photos TEXT DEFAULT '', ship_at INTEGER, recv_photos TEXT DEFAULT '', recv_at INTEGER,
        recv_cond TEXT DEFAULT '', recv_note TEXT DEFAULT '', purchase_id INTEGER, expect_date TEXT DEFAULT '');
    CREATE INDEX IF NOT EXISTS idx_moves ON asset_moves(status, kind);
    CREATE TABLE IF NOT EXISTS purchases(
        id INTEGER PRIMARY KEY, item_id INTEGER, name TEXT, price REAL, qty INTEGER, buy_date TEXT, expect_date TEXT,
        note TEXT DEFAULT '', created_by TEXT, created_at INTEGER);
    CREATE TABLE IF NOT EXISTS count_tasks(
        id INTEGER PRIMARY KEY, name TEXT, ctype TEXT, stores TEXT, items TEXT, mode TEXT, rules TEXT,
        start_date TEXT, end_date TEXT, review_date TEXT, status TEXT NOT NULL DEFAULT 'open',
        created_by TEXT, created_at INTEGER, closed_at INTEGER, summary TEXT DEFAULT '');
    CREATE TABLE IF NOT EXISTS count_lines(
        id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, asset_id INTEGER, store TEXT,
        status TEXT NOT NULL DEFAULT 'todo',          -- todo / ok 符合 / doubt 存疑 / fail 不符合 / missing 找不到 / extra 盘盈
        cond TEXT DEFAULT '', photo TEXT DEFAULT '', ai TEXT DEFAULT '', note TEXT DEFAULT '', at INTEGER,
        review TEXT DEFAULT '', review_note TEXT DEFAULT '', extra_name TEXT DEFAULT '', extra_no TEXT DEFAULT '');
    CREATE INDEX IF NOT EXISTS idx_count_lines ON count_lines(task_id, store);
    CREATE TABLE IF NOT EXISTS count_submits(task_id INTEGER, store TEXT, at INTEGER, PRIMARY KEY(task_id, store));
    """)
    for k, v in ASSET_SETTING_DEFAULTS.items():
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?,?)", (k, v))
    import secrets as _s
    conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES('photo_secret', ?)", (_s.token_hex(16),))


# (版本号, 说明, SQL 字串 或 函数(conn))
# ⚠ 只能在末尾追加，不能修改已发布的项目。
MIGRATIONS = [
    (1, "初始资料结构（账号、人员、支援记录、确认签名、登录会话、操作日志）", SCHEMA_V1),
    (2, "支援记录新增「工时调整」栏位（归档后由一方提出、另一方确认）",
     "ALTER TABLE requests ADD COLUMN adj_start TEXT DEFAULT NULL;"
     "ALTER TABLE requests ADD COLUMN adj_end TEXT DEFAULT NULL;"
     "ALTER TABLE requests ADD COLUMN adj_hours REAL DEFAULT NULL;"
     "ALTER TABLE requests ADD COLUMN adj_by TEXT DEFAULT NULL;"
     "ALTER TABLE requests ADD COLUMN adj_note TEXT DEFAULT NULL;"
     "ALTER TABLE requests ADD COLUMN adj_at INTEGER DEFAULT NULL;"
     "CREATE INDEX IF NOT EXISTS idx_req_adj ON requests(adj_by)"),
    (3, "工时拆分与补贴：营业时间、法定节假日、补贴设定、门店定位、营运/非营运工时、夜班与长途补贴", _migrate_v3),
    (4, "长途改用驾车距离：两店距离快取表；人资可指定两店是否长途", _migrate_v4),
    (5, "资产管理模块：资产目录、资产、履历、照片、调拨 / 报废 / 入库、财务购入、盘点", _migrate_v5),
    # 范例（未来新增栏位时）：
    # (4, "支援记录新增班别栏位", "ALTER TABLE requests ADD COLUMN shift TEXT NOT NULL DEFAULT '';"),
]

LATEST = MIGRATIONS[-1][0]


def connect(path):
    conn = sqlite3.connect(path, timeout=15, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _ensure_meta(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)")


def current_version(conn):
    _ensure_meta(conn)
    row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
    return row["v"] or 0


def backup(path, tag="manual", keep=60):
    """用 SQLite 线上备份 API 复制资料库（服务运行中也安全）。"""
    if not os.path.exists(path):
        return None
    folder = os.path.join(os.path.dirname(os.path.abspath(path)), "backups")
    os.makedirs(folder, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(folder, "%s_%s_%s.db" % (os.path.splitext(os.path.basename(path))[0], stamp, tag))
    src = sqlite3.connect(path)
    dst = sqlite3.connect(dest)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    # 只保留最近 keep 份同类备份
    files = sorted(f for f in os.listdir(folder) if f.endswith("_%s.db" % tag))
    for f in files[:-keep]:
        try:
            os.remove(os.path.join(folder, f))
        except OSError:
            pass
    return dest


def migrate(path, do_backup=True, log=print):
    """套用所有尚未执行的迁移。回传 (旧版本, 新版本)。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    existed = os.path.exists(path)
    conn = connect(path)
    try:
        before = current_version(conn)
        if before > LATEST:
            raise RuntimeError("资料库版本 v%d 比程式支援的 v%d 新，请更新程式，不要用旧程式开启新资料库。" % (before, LATEST))
        pending = [m for m in MIGRATIONS if m[0] > before]
        if not pending:
            return before, before
        if existed and before > 0 and do_backup:
            dest = backup(path, tag="before_v%d" % pending[0][0], keep=20)
            log("已备份资料库：%s" % dest)
        for ver, name, step in pending:
            log("套用迁移 v%d：%s" % (ver, name))
            conn.execute("BEGIN IMMEDIATE")
            try:
                if callable(step):
                    step(conn)
                else:
                    for stmt in [s.strip() for s in step.split(";") if s.strip()]:
                        conn.execute(stmt)
                conn.execute("INSERT INTO schema_migrations(version, name, applied_at) VALUES(?,?,?)",
                             (ver, name, datetime.datetime.now().isoformat(timespec="seconds")))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return before, current_version(conn)
    finally:
        conn.close()


def status(path):
    if not os.path.exists(path):
        return {"exists": False, "version": 0, "latest": LATEST, "applied": []}
    conn = connect(path)
    try:
        v = current_version(conn)
        applied = [dict(r) for r in conn.execute("SELECT * FROM schema_migrations ORDER BY version")]
        return {"exists": True, "version": v, "latest": LATEST, "applied": applied}
    finally:
        conn.close()
