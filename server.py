# -*- coding: utf-8 -*-
"""
1点点 跨店支援工时系统 — 服务端（只用 Python 标准库，Python 3.8 以上）

启动：python server.py
设定：同目录 config.json（可选），见 README。
"""
import os
import re
import sys
import json
import time
import base64
import hashlib
import secrets
import datetime
import threading
import traceback
from urllib.parse import urlparse, parse_qs, quote
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

import db
import xlsx
import rules

APP_VERSION = "1.2.5"
HERE = os.path.dirname(os.path.abspath(__file__))

CFG = {
    "host": "0.0.0.0",
    "port": 8080,
    "db_path": "data/support.db",
    "log_retention_days": 60,      # 操作日志保留天数（两个月）
    "session_days": 60,            # 登录状态保留天数
    "trust_proxy": False,          # 若架在 Nginx 等反向代理之后，设为 true 以读取真实 IP
    "daily_backup": True,          # 每日自动备份资料库
    "backup_keep": 30,             # 每日备份保留份数
    "demo": False,                 # 演示版：登录页列出示范账号、画面显示「演示版」
    "demo_note": "演示版 · 资料为示范用途，每天凌晨 4 点自动重置",
    "demo_keys_from": "",          # 演示版：重置时从这个正式版资料库复制高德金钥（只读）
}
_cfg_file = os.path.join(HERE, "config.json")
if os.path.exists(_cfg_file):
    with open(_cfg_file, encoding="utf-8") as _f:
        CFG.update(json.load(_f))
DB_PATH = CFG["db_path"] if os.path.isabs(CFG["db_path"]) else os.path.join(HERE, CFG["db_path"])

CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,30}$")
STATUS = {"pending": "待对方确认", "approved": "已归档", "rejected": "已驳回", "withdrawn": "已撤回",
          "disputed": "疑义待人资处理", "cancelled": "人资已取消"}
LIVE = ("pending", "approved", "disputed")
REASONS = ["人手不足", "伙伴请假顶班", "新店开业", "促销活动", "培训带教", "其他", "员工请假顶班"]  # 最后一项保留给旧版


def now_ms():
    return int(time.time() * 1000)


def fmt_ts(ms):
    return datetime.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M") if ms else ""


class ApiError(Exception):
    def __init__(self, msg, status=400):
        Exception.__init__(self, msg)
        self.status = status


# ---------------------------------------------------------------- 装置识别
def parse_device(ua, hint=""):
    ua = ua or ""
    hint = (hint or "").strip()[:60]
    app = ""
    if "MicroMessenger" in ua:
        app = "微信"
    elif "DingTalk" in ua:
        app = "钉钉"
    elif "AlipayClient" in ua:
        app = "支付宝"
    dev = "其他装置"
    m = re.search(r"iPhone OS (\d+)_(\d+)", ua)
    if "iPhone" in ua:
        dev = "iPhone" + (" · iOS %s.%s" % m.groups() if m else "")
    elif "iPad" in ua:
        dev = "iPad"
    elif "HarmonyOS" in ua or "OpenHarmony" in ua:
        mm = re.search(r";\s*([^;()]+?)\s+Build/", ua)
        dev = "鸿蒙" + (" · " + mm.group(1) if mm else "")
    elif "Android" in ua:
        mm = re.search(r"Android\s*([\d.]*)\s*;(.*?)\)", ua)
        ver, model = "", ""
        if mm:
            ver = mm.group(1)
            segs = [s.strip() for s in mm.group(2).split(";")]
            segs = [s for s in segs if s and s not in ("wv", "K", "U") and not re.match(r"^[a-z]{2}[-_][a-zA-Z]{2}$", s)]
            if segs:
                model = segs[0].split(" Build")[0].strip()
        dev = (model or "Android") + (" · Android %s" % ver if ver else "")
    elif "Windows" in ua:
        dev = "Windows 电脑"
    elif "Macintosh" in ua:
        dev = "Mac 电脑"
    elif "Linux" in ua:
        dev = "Linux 电脑"
    if hint and hint not in dev:
        dev = hint + " · " + dev
    return dev + (" · " + app if app else "")


# ---------------------------------------------------------------- 资料库辅助
def rows(conn, sql, args=()):
    return [dict(r) for r in conn.execute(sql, args)]


def one(conn, sql, args=()):
    r = conn.execute(sql, args).fetchone()
    return dict(r) if r else None


class Tx(object):
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, et, ev, tb):
        self.conn.execute("COMMIT" if et is None else "ROLLBACK")
        return False


def write_log(conn, req, action, detail="", code=None, role=None):
    me = req.me or {}
    conn.execute("INSERT INTO logs(t, code, role, action, detail, ip, device, ua) VALUES(?,?,?,?,?,?,?,?)",
                 (now_ms(), code or me.get("code", ""), role or me.get("role", ""), action, detail,
                  req.ip, req.device, (req.ua or "")[:300]))


def acc_name(conn, code, cache={}):
    r = one(conn, "SELECT name FROM accounts WHERE code=?", (code,))
    return r["name"] if r else code


def month_sig(conn, month, code):
    ids = rows(conn, """SELECT id, hours, op_hours, non_hours, night_pay, long_pay FROM requests
                        WHERE month=? AND status='approved' AND (from_store=? OR to_store=?)""", (month, code, code))
    s = "|".join(sorted("%d:%s:%s:%s:%s:%s" % (r["id"], r["hours"], r["op_hours"], r["non_hours"], r["night_pay"], r["long_pay"]) for r in ids))
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def slot_idx(t):
    if t == "24:00":
        return 48
    m = re.match(r"^(\d\d):(00|30)$", t or "")
    if not m or int(m.group(1)) > 23:
        raise ApiError("时间须为 30 分钟为单位（例如 09:00、09:30）")
    return int(m.group(1)) * 2 + (1 if m.group(2) == "30" else 0)


def valid_month(m):
    if not re.match(r"^\d{4}-\d{2}$", m or ""):
        raise ApiError("月份格式不正确")
    return m


def add_event(conn, rid, who, act, note=""):
    conn.execute("INSERT INTO request_events(request_id, t, who, act, note) VALUES(?,?,?,?,?)", (rid, now_ms(), who, act, note or ""))


def with_events(conn, reqs):
    if not reqs:
        return reqs
    ids = [r["id"] for r in reqs]
    ev = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        for e in rows(conn, "SELECT * FROM request_events WHERE request_id IN (%s) ORDER BY id" % ",".join("?" * len(chunk)), chunk):
            ev.setdefault(e["request_id"], []).append(e)
    for r in reqs:
        r["events"] = ev.get(r["id"], [])
    return reqs


# ---------------------------------------------------------------- 路由
ROUTES = []


def route(method, pattern, auth="any"):
    """auth: None=不需登录, 'any'=已登录, 'store', 'hr'"""
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), auth, fn))
        return fn
    return deco


class Req(object):
    pass


# ---- 基础 / 登录 ----------------------------------------------------------
@route("GET", "/api/bootstrap", auth=None)
def api_bootstrap(req):
    has_hr = one(req.conn, "SELECT 1 AS x FROM accounts WHERE role='hr' LIMIT 1") is not None
    out = {"hasHR": has_hr, "version": APP_VERSION, "schema": db.current_version(req.conn)}
    if CFG.get("demo"):
        out["demo"] = CFG.get("demo_note") or "演示版"
        out["demoAccounts"] = rows(req.conn, """SELECT code, name, role FROM accounts WHERE active=1 AND role IN ('hr','store')
                                                ORDER BY CASE role WHEN 'hr' THEN 0 ELSE 1 END, code""")
    return out


@route("POST", "/api/setup", auth=None)
def api_setup(req):
    code = (req.body.get("code") or "").strip()
    name = (req.body.get("name") or "").strip() or "人资部"
    if not CODE_RE.match(code):
        raise ApiError("账号只能用英文字母、数字、-、_")
    with Tx(req.conn) as c:
        if one(c, "SELECT 1 AS x FROM accounts WHERE role='hr' LIMIT 1"):
            raise ApiError("系统已初始化", 409)
        c.execute("INSERT INTO accounts(code, name, role, active, created_at, updated_at) VALUES(?,?,?,?,?,?)",
                  (code, name, "hr", 1, now_ms(), now_ms()))
        write_log(c, req, "初始化", "建立人资账号 %s" % code, code=code, role="hr")
    return api_login(req)


@route("POST", "/api/login", auth=None)
def api_login(req):
    code = (req.body.get("code") or "").strip()
    acc = one(req.conn, "SELECT * FROM accounts WHERE code=? COLLATE NOCASE", (code,))
    if not acc:
        write_log(req.conn, req, "登录失败", "账号不存在：%s" % code[:30], code=code[:30], role="")
        raise ApiError("账号不存在，请确认门店编号")
    if not acc["active"]:
        write_log(req.conn, req, "登录失败", "账号已停用", code=acc["code"], role=acc["role"])
        raise ApiError("该账号已停用，请联系人资")
    if acc["role"] == "hq":
        raise ApiError("总部账号仅用于记录地址，不能登录；总部的支援由人资确认")
    token = secrets.token_urlsafe(32)
    with Tx(req.conn) as c:
        c.execute("INSERT INTO sessions(token, code, created_at, last_seen, ip, device) VALUES(?,?,?,?,?,?)",
                  (token, acc["code"], now_ms(), now_ms(), req.ip, req.device))
        req.me = acc
        write_log(c, req, "登录", "")
    return {"token": token, "me": public_me(acc)}


def public_me(acc):
    return {"code": acc["code"], "name": acc["name"], "role": acc["role"]}


@route("POST", "/api/logout")
def api_logout(req):
    req.conn.execute("DELETE FROM sessions WHERE token=?", (req.token,))
    write_log(req.conn, req, "退出", "")
    return {"ok": True}


@route("GET", "/api/me")
def api_me(req):
    need = req.me["role"] == "store" and not profile_complete(req.conn, req.me["code"])
    return {"me": public_me(req.me), "version": APP_VERSION, "needProfile": need,
            "demo": (CFG.get("demo_note") or "演示版") if CFG.get("demo") else ""}


@route("POST", "/api/client-log")
def api_client_log(req):
    act = (req.body.get("action") or "")[:30]
    if act in ("查看页面",):
        write_log(req.conn, req, act, (req.body.get("detail") or "")[:100])
    return {"ok": True}


# ---- 共用资料 --------------------------------------------------------------
@route("GET", "/api/accounts")
def api_accounts(req):
    cols = "code, name, role, active, phone, address, lat, lng" if req.me["role"] == "hr" else "code, name, role, active"
    return {"accounts": rows(req.conn, "SELECT %s FROM accounts ORDER BY role DESC, code" % cols)}


@route("GET", "/api/staff")
def api_staff(req):
    store = req.q.get("store")
    if req.me["role"] != "hr" and not store:
        raise ApiError("缺少门店")
    if store:
        return {"staff": rows(req.conn, "SELECT id, store, name, emp_no, active FROM staff WHERE store=? ORDER BY active DESC, name", (store,))}
    return {"staff": rows(req.conn, "SELECT id, store, name, emp_no, active FROM staff ORDER BY store, active DESC, name")}


# ---- 门店：首页 -------------------------------------------------------------
def tot_hours(r):
    return (r.get("op_hours") if r.get("op_hours") is not None else r["hours"]) + (r.get("non_hours") or 0)


@route("GET", "/api/home", auth="store")
def api_home(req):
    code = req.me["code"]
    c = req.conn
    inbox = with_events(c, rows(c, "SELECT * FROM requests WHERE counterparty=? AND status='pending' ORDER BY date, start_time", (code,)))
    outbox = rows(c, "SELECT * FROM requests WHERE initiator=? AND status='pending' ORDER BY date, start_time", (code,))
    adj_in = with_events(c, rows(c, """SELECT * FROM requests WHERE status='approved' AND adj_by IS NOT NULL AND adj_by<>?
                                      AND (from_store=? OR to_store=?) ORDER BY date, start_time""", (code, code, code)))
    adj_out = rows(c, "SELECT * FROM requests WHERE status='approved' AND adj_by=? ORDER BY date, start_time", (code,))
    month = datetime.date.today().strftime("%Y-%m")
    ap = rows(c, "SELECT * FROM requests WHERE month=? AND status='approved' AND (from_store=? OR to_store=?)", (month, code, code))
    s = {"out_h": sum(tot_hours(r) for r in ap if r["from_store"] == code),
         "in_h": sum(tot_hours(r) for r in ap if r["to_store"] == code), "n": len(ap)}
    remind = None
    today = datetime.date.today()
    if today.day <= 10:
        prev = (today.replace(day=1) - datetime.timedelta(days=1)).strftime("%Y-%m")
        info = close_info(c, prev, code)
        if info["involved"] and not info["valid"]:
            remind = prev
    return {"inbox": inbox, "outbox": outbox, "adjIn": adj_in, "adjOut": adj_out, "month": month, "summary": s, "remindMonth": remind}


# ---- 门店资料（营业时间、地址定位） -------------------------------------------
def profile_complete(c, code):
    a = one(c, "SELECT lat, address FROM accounts WHERE code=?", (code,))
    has_hours = one(c, "SELECT 1 AS x FROM store_hours WHERE store=? AND days='' LIMIT 1", (code,)) is not None
    return bool(a and a["lat"] is not None and a["address"] and has_hours)


@route("GET", "/api/store/profile")
def api_profile_get(req):
    c = req.conn
    code = req.q.get("store") if req.me["role"] == "hr" and req.q.get("store") else req.me["code"]
    a = one(c, "SELECT code, name, role, address, lat, lng FROM accounts WHERE code=?", (code,))
    if not a:
        raise ApiError("账号不存在", 404)
    cfg = rules.load_settings(c)
    hours = [{"days": [int(x) for x in h["days"].split(",") if x != ""], "open": h["open_time"], "close": h["close_time"]}
             for h in rules.store_hours(c, code)]
    return {"account": a, "hours": hours, "complete": profile_complete(c, code) if a["role"] == "store" else a["lat"] is not None,
            "editable": req.me["role"] == "hr" or not profile_complete(c, code),
            "amapKey": cfg["amap_key"], "amapSec": cfg["amap_sec"], "prepMin": int(cfg["prep_min"]), "cleanMin": int(cfg["clean_min"])}


@route("POST", "/api/store/profile")
def api_profile_save(req):
    c, b = req.conn, req.body
    is_hr = req.me["role"] == "hr"
    code = (b.get("store") or "") if is_hr else req.me["code"]
    a = one(c, "SELECT * FROM accounts WHERE code=?", (code,))
    if not a:
        raise ApiError("账号不存在", 404)
    if not is_hr and profile_complete(c, code):
        raise ApiError("门店资料已建立，如需修改请联系人资", 403)
    address = (b.get("address") or "").strip()[:120]
    try:
        lat, lng = float(b.get("lat")), float(b.get("lng"))
    except (TypeError, ValueError):
        raise ApiError("请在地图上确认门店位置（或填写经纬度）")
    if not (3 < lat < 54 and 73 < lng < 136):
        raise ApiError("经纬度不在中国范围内，请确认")
    if b.get("coordSys") == "gps":
        lat, lng = rules.wgs84_to_gcj02(lat, lng)
        lat, lng = round(lat, 6), round(lng, 6)
    if not address:
        raise ApiError("请填写地址")
    hours = b.get("hours") or []
    clean = []
    if a["role"] != "hq":
        if not hours:
            raise ApiError("请填写营业时间")
        for i, h in enumerate(hours):
            days = sorted(set(int(x) for x in (h.get("days") or []) if 0 <= int(x) <= 7))
            if i == 0:
                days = []
            elif not days:
                raise ApiError("第 %d 组营业时间请选择适用的星期" % (i + 1))
            o, cl = rules.tmin(h.get("open") or "0:0"), rules.tmin(h.get("close") or "0:0")
            if not (0 <= o < 1440 and o < cl <= rules.MAX_END):
                raise ApiError("营业时间不正确（结束需晚于开始，最晚到次日 06:00）")
            clean.append((",".join(str(d) for d in days), h["open"], h["close"], i))
    with Tx(c):
        moved = a["lat"] is None or abs((a["lat"] or 0) - lat) > 1e-6 or abs((a["lng"] or 0) - lng) > 1e-6
        c.execute("UPDATE accounts SET address=?, lat=?, lng=?, updated_at=? WHERE code=?", (address, lat, lng, now_ms(), code))
        if moved:   # 位置改变：清除与此店有关的距离，下次重新计算（人资的长途指定保留）
            c.execute("DELETE FROM store_distances WHERE a=? OR b=?", (code, code))
        if a["role"] != "hq":
            c.execute("DELETE FROM store_hours WHERE store=?", (code,))
            for d, o, cl, i in clean:
                c.execute("INSERT INTO store_hours(store, days, open_time, close_time, sort) VALUES(?,?,?,?,?)", (code, d, o, cl, i))
        desc = "；".join(("每天" if not d else "、".join(rules.DAY_NAMES[int(x)] for x in d.split(","))) + " " + o + "–" + rules.tlabel(rules.tmin(cl)) for d, o, cl, i in clean)
        write_log(c, req, "门店资料", "%s：%s；%s（%.5f, %.5f）" % (a["name"], desc or "总部", address, lat, lng))
    return {"ok": True}


# ---- 门店：试算与发起 -------------------------------------------------------
def parse_times(start, end):
    for t in (start, end):
        if not re.match(r"^\d\d:(00|30)$", t or ""):
            raise ApiError("时间须为 30 分钟为单位（例如 09:00、09:30）")
    s, e = rules.tmin(start), rules.tmin(end)
    if s >= 1440:
        raise ApiError("开始时间不正确")
    if e <= s:
        raise ApiError("结束时间必须晚于开始时间")
    if e > rules.MAX_END:
        raise ApiError("结束时间最晚到次日 06:00")
    return s, e


def resolve_parties(c, me, kind, other):
    if kind not in ("out", "in"):
        raise ApiError("请选择调出或调入")
    oacc = one(c, "SELECT * FROM accounts WHERE code=? AND role IN ('store','hq') AND active=1", (other,))
    if not oacc or other == me:
        raise ApiError("请选择有效的对方门店")
    if oacc["role"] == "hq" and kind != "out":
        raise ApiError("总部只能选「调出」（本店伙伴去总部）")
    return oacc, ((me, other) if kind == "out" else (other, me))


def calc_view(c, x):
    v = {k: x[k] for k in ("nature", "special", "holiday", "op_hours", "non_hours", "night_hours", "night_pay", "long_km", "long_pay",
                           "out_of_hours", "hours", "lunch_hours", "to_hq", "dist_source", "dist_error", "long_override")}
    v["total"] = x["op_hours"] + x["non_hours"]
    v["sub"] = x["night_pay"] + x["long_pay"]
    v["bh"], v["notes"], v["payer"], v["payer_name"] = x["bh"], x["notes"], x["payer"], acc_name(c, x["payer"])
    return v


@route("POST", "/api/preview", auth="store")
def api_preview(req):
    b, c, me = req.body, req.conn, req.me["code"]
    oacc, (fs, ts) = resolve_parties(c, me, b.get("kind"), (b.get("store") or "").strip())
    parse_times(b.get("start"), b.get("end"))
    x = rules.compute(c, {"date": b.get("date") or "", "start_time": b["start"], "end_time": b["end"], "from_store": fs, "to_store": ts,
                          "nature": b.get("nature") or "op", "special": b.get("special") or ""})
    return calc_view(c, x)


def check_overlap(c, staff_id, name, date, s, e, exclude=0):
    for o in rows(c, "SELECT start_time, end_time FROM requests WHERE staff_id=? AND date=? AND id<>? AND status IN ('pending','approved','disputed')",
                  (staff_id, date, exclude)):
        if rules.tmin(o["start_time"]) < e and s < rules.tmin(o["end_time"]):
            raise ApiError("%s 在 %s %s–%s 已有支援记录" % (name, date, o["start_time"], rules.tlabel(rules.tmin(o["end_time"]))))


def apply_calc(c, rid, cfg=None):
    r = one(c, "SELECT * FROM requests WHERE id=?", (rid,))
    x = rules.compute(c, r, cfg)
    sets = ", ".join("%s=?" % k for k in rules.CALC_COLS)
    c.execute("UPDATE requests SET %s, hours=? WHERE id=?" % sets, [x[k] for k in rules.CALC_COLS] + [x["hours"], rid])
    return x


@route("POST", "/api/requests", auth="store")
def api_create(req):
    b, c, me = req.body, req.conn, req.me["code"]
    kind = b.get("kind")
    other = (b.get("store") or "").strip()
    date = b.get("date") or ""
    start, end = b.get("start") or "", b.get("end") or ""
    ids = [int(x) for x in (b.get("staffIds") or [])]
    reason = b.get("reason") if b.get("reason") in REASONS else "其他"
    note = (b.get("note") or "").strip()[:100]
    special = b.get("special") or ""
    if special and special not in rules.SPECIALS:
        raise ApiError("特殊状况不正确")
    nature = "non" if b.get("nature") == "non" else "op"     # 进阶设定：发起时直接选非营运
    if nature == "non" and special not in rules.NON_ITEMS:
        raise ApiError("请选择非营运项目（开会、大扫除、筹备、培训）")
    if nature == "op" and special in rules.NON_ITEMS:
        nature = "non"
    oacc, (from_store, to_store) = resolve_parties(c, me, kind, other)
    try:
        d = datetime.date.fromisoformat(date)
    except ValueError:
        raise ApiError("请选择日期")
    if abs((d - datetime.date.today()).days) > 62:
        raise ApiError("日期须在前后两个月内")
    s, e = parse_times(start, end)
    if not ids:
        raise ApiError("请至少选择一位伙伴")
    src = me if kind == "out" else other
    probe = rules.compute(c, {"date": date, "start_time": start, "end_time": end, "from_store": from_store, "to_store": to_store,
                              "nature": nature, "special": special})
    if probe["out_of_hours"] and not special:
        raise ApiError("支援时间超出对方门店营业时间，请选择特殊状况", 409)
    created = []
    with Tx(c):
        people = []
        for sid in ids:
            p = one(c, "SELECT * FROM staff WHERE id=?", (sid,))
            if not p or p["store"] != src or not p["active"]:
                raise ApiError("所选伙伴不属于%s或已离职" % ("本店" if kind == "out" else "对方门店"))
            check_overlap(c, sid, p["name"], date, s, e)
            people.append(p)
        fn, tn = acc_name(c, from_store), acc_name(c, to_store)
        for p in people:
            cur = c.execute("""INSERT INTO requests(month, date, start_time, end_time, hours, from_store, to_store, from_name, to_name,
                               staff_id, staff_name, staff_emp_no, initiator, counterparty, kind, reason, note, status, created_at, updated_at, special, nature)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (date[:7], date, start, end, (e - s) / 60.0, from_store, to_store, fn, tn, p["id"], p["name"], p["emp_no"] or "",
                             me, other, kind, reason, note, "pending", now_ms(), now_ms(), special, nature))
            rid = cur.lastrowid
            x = apply_calc(c, rid)
            created.append(rid)
            add_event(c, rid, me, ("发起调出" if kind == "out" else "发起调入") + ("（%s）" % nature_text(nature, special) if special else ""))
        write_log(c, req, "发起支援", "%s %s %s–%s %s %s%s，%s（%d 人）" % (
            "调出至" if kind == "out" else "调入自", oacc["name"], start, rules.tlabel(e), date, reason,
            "；特殊状况：" + special if special else "", "、".join(p["name"] for p in people), len(people)))
    return {"created": created, "hours": x["hours"]}


def load_req(c, rid):
    r = one(c, "SELECT * FROM requests WHERE id=?", (rid,))
    if not r:
        raise ApiError("记录不存在", 404)
    return r


def req_desc(r):
    return "#%d %s %s %s–%s %s→%s" % (r["id"], r["staff_name"], r["date"], r["start_time"], rules.tlabel(rules.tmin(r["end_time"])), r["from_name"], r["to_name"])


def can_act_as(req, code):
    """本人门店，或对方是总部时由人资代为确认。"""
    return req.me["code"] == code or (req.me["role"] == "hr" and rules.is_hq(req.conn, code))


def nature_text(nature, special):
    return ("非营运" + ("·" + special if special else "")) if nature == "non" else ("营运" + ("·" + special if special else ""))


@route("POST", r"/api/requests/(\d+)/(approve|reject|withdraw|dispute|cancel|keep|adjust|adjust_ok|adjust_no|adjust_cancel|edit)")
def api_act(req):
    rid, act = int(req.args[0]), req.args[1]
    note = (req.body.get("note") or "").strip()[:200]
    me, role, c = req.me["code"], req.me["role"], req.conn
    with Tx(c):
        r = load_req(c, rid)
        t = now_ms()
        if act in ("approve", "reject"):
            if not can_act_as(req, r["counterparty"]):
                raise ApiError("只有对方门店可以审核", 403)
            if r["status"] != "pending":
                raise ApiError("该申请已被处理（%s）" % STATUS.get(r["status"]), 409)
            if act == "reject" and not note:
                raise ApiError("请填写驳回原因")
            new = "approved" if act == "approve" else "rejected"
            c.execute("UPDATE requests SET status=?, decided_at=?, updated_at=? WHERE id=?", (new, t, t, rid))
            if act == "approve":
                label = "总部同意（人资）" if role == "hr" else ("同意调出" if r["from_store"] == me else "同意调入")
            else:
                label = "驳回"
            add_event(c, rid, me, label, note)
            write_log(c, req, label, req_desc(r) + ("；原因：" + note if note else ""))
        elif act == "withdraw":
            if r["initiator"] != me:
                raise ApiError("只有发起门店可以撤回", 403)
            if r["status"] != "pending":
                raise ApiError("对方已处理，无法撤回", 409)
            c.execute("UPDATE requests SET status='withdrawn', updated_at=? WHERE id=?", (t, rid))
            add_event(c, rid, me, "撤回")
            write_log(c, req, "撤回", req_desc(r))
        elif act == "edit":
            if r["initiator"] != me or r["status"] != "pending":
                raise ApiError("只有发起门店在对方确认前可以直接修改", 403)
            nature = "non" if req.body.get("nature") == "non" else "op"
            special = req.body.get("special") or ""
            if special and special not in rules.SPECIALS:
                raise ApiError("项目不正确")
            if nature == "non" and special not in rules.NON_ITEMS:
                raise ApiError("请选择非营运项目")
            if nature == "op" and special in rules.NON_ITEMS:
                special = ""
            if r["out_of_hours"] and not special:
                raise ApiError("这笔超出营业时间，请保留一项特殊状况")
            c.execute("UPDATE requests SET nature=?, special=?, updated_at=? WHERE id=?", (nature, special, t, rid))
            x = apply_calc(c, rid)
            chg = "%s → %s" % (nature_text(r["nature"], r["special"]), nature_text(x["nature"], x["special"]))
            add_event(c, rid, me, "修改支援性质", chg)
            write_log(c, req, "修改支援性质", req_desc(r) + "；" + chg)
        elif act == "dispute":
            if role != "store" or me not in (r["from_store"], r["to_store"]):
                raise ApiError("无权操作", 403)
            if r["status"] != "approved":
                raise ApiError("只有已归档的记录可以提出疑义", 409)
            if not note:
                raise ApiError("请说明疑义原因")
            if r["adj_by"]:
                raise ApiError("这笔记录有工时调整待确认，请先处理调整", 409)
            info = close_info(c, r["month"], me)
            if info["valid"]:
                raise ApiError("本店该月已签名确认，如需提出疑义请先请人资退回确认", 409)
            c.execute("UPDATE requests SET status='disputed', dispute_by=?, dispute_note=?, dispute_at=?, updated_at=? WHERE id=?",
                      (me, note, t, t, rid))
            add_event(c, rid, me, "提出疑义", note)
            write_log(c, req, "提出疑义", req_desc(r) + "；" + note)
        elif act == "adjust":
            if role != "store" or me not in (r["from_store"], r["to_store"]):
                raise ApiError("无权操作", 403)
            if r["status"] != "approved":
                raise ApiError("只有已归档的记录可以调整", 409)
            if r["adj_by"]:
                raise ApiError("这笔记录已有调整待确认", 409)
            if close_info(c, r["month"], me)["valid"]:
                raise ApiError("本店该月已签名确认，如需调整请先请人资退回确认", 409)
            start = req.body.get("start") or r["start_time"]
            end = req.body.get("end") or r["end_time"]
            s, e = parse_times(start, end)
            nature = "non" if req.body.get("nature") == "non" else "op"
            special = req.body.get("special") if req.body.get("special") is not None else r["special"]
            if special and special not in rules.SPECIALS:
                raise ApiError("项目不正确")
            if nature == "non" and special not in rules.NON_ITEMS:
                raise ApiError("请选择非营运项目")
            if nature == "op" and special in rules.NON_ITEMS:
                special = ""
            if start == r["start_time"] and end == r["end_time"] and nature == r["nature"] and special == r["special"]:
                raise ApiError("内容没有变化")
            if not note:
                raise ApiError("请填写调整原因")
            check_overlap(c, r["staff_id"], r["staff_name"], r["date"], s, e, exclude=rid)
            probe = rules.compute(c, dict(r, start_time=start, end_time=end, nature=nature, special=special))
            if probe["out_of_hours"] and not special:
                raise ApiError("调整后超出营业时间，请选择特殊状况", 409)
            c.execute("""UPDATE requests SET adj_start=?, adj_end=?, adj_hours=?, adj_nature=?, adj_special=?, adj_by=?, adj_note=?, adj_at=?, updated_at=?
                         WHERE id=?""", (start, end, probe["op_hours"] + probe["non_hours"], nature, special, me, note, t, t, rid))
            chg = "%s–%s %s（%g 小时）→ %s–%s %s（%g 小时）" % (
                r["start_time"], rules.tlabel(rules.tmin(r["end_time"])), nature_text(r["nature"], r["special"]), tot_hours(r),
                start, rules.tlabel(e), nature_text(probe["nature"], probe["special"]), probe["op_hours"] + probe["non_hours"])
            add_event(c, rid, me, "提出调整", chg + "；" + note)
            write_log(c, req, "提出调整", req_desc(r) + "；" + chg + "；" + note)
        elif act in ("adjust_ok", "adjust_no"):
            if not r["adj_by"] or r["status"] != "approved":
                raise ApiError("没有待确认的调整", 409)
            other = r["to_store"] if r["adj_by"] == r["from_store"] else r["from_store"]
            if not can_act_as(req, other):
                raise ApiError("只有对方门店可以确认调整", 403)
            if act == "adjust_no" and not note:
                raise ApiError("请填写驳回原因")
            chg = "%s–%s → %s–%s（%s，%g 小时）" % (r["start_time"], rules.tlabel(rules.tmin(r["end_time"])), r["adj_start"],
                                                   rules.tlabel(rules.tmin(r["adj_end"])), nature_text(r["adj_nature"] or r["nature"], r["adj_special"] or ""), r["adj_hours"])
            clear = "adj_start=NULL, adj_end=NULL, adj_hours=NULL, adj_nature=NULL, adj_special=NULL, adj_by=NULL, adj_note=NULL, adj_at=NULL"
            if act == "adjust_ok":
                c.execute("UPDATE requests SET start_time=?, end_time=?, nature=?, special=?, %s, updated_at=? WHERE id=?" % clear,
                          (r["adj_start"], r["adj_end"], r["adj_nature"] or r["nature"], r["adj_special"] if r["adj_special"] is not None else r["special"], t, rid))
                apply_calc(c, rid)
                add_event(c, rid, me, "同意工时调整", chg)
                write_log(c, req, "同意工时调整", req_desc(r) + "；" + chg)
            else:
                c.execute("UPDATE requests SET %s, updated_at=? WHERE id=?" % clear, (t, rid))
                add_event(c, rid, me, "驳回工时调整", note)
                write_log(c, req, "驳回工时调整", req_desc(r) + "；" + chg + "；原因：" + note)
        elif act == "adjust_cancel":
            if r["adj_by"] != me:
                raise ApiError("只有提出调整的门店可以撤回", 403)
            c.execute("""UPDATE requests SET adj_start=NULL, adj_end=NULL, adj_hours=NULL, adj_nature=NULL, adj_special=NULL, adj_by=NULL,
                         adj_note=NULL, adj_at=NULL, updated_at=? WHERE id=?""", (t, rid))
            add_event(c, rid, me, "撤回工时调整")
            write_log(c, req, "撤回工时调整", req_desc(r))
        else:
            if role != "hr":
                raise ApiError("只有人资可以处理疑义", 403)
            if r["status"] != "disputed":
                raise ApiError("该记录不在疑义状态", 409)
            new = "cancelled" if act == "cancel" else "approved"
            label = "人资同意取消" if act == "cancel" else "维持记录"
            c.execute("UPDATE requests SET status=?, updated_at=? WHERE id=?", (new, t, rid))
            add_event(c, rid, me, label, note)
            write_log(c, req, label, req_desc(r) + ("；" + note if note else ""))
    return {"ok": True}


# ---- 记录查询 -------------------------------------------------------------
@route("GET", "/api/requests")
def api_list(req):
    month = valid_month(req.q.get("month"))
    c = req.conn
    if req.me["role"] == "hr":
        store = req.q.get("store")
        if store:
            data = rows(c, "SELECT * FROM requests WHERE month=? AND (from_store=? OR to_store=?) ORDER BY date DESC, start_time DESC", (month, store, store))
        else:
            data = rows(c, "SELECT * FROM requests WHERE month=? ORDER BY date DESC, start_time DESC", (month,))
    else:
        me = req.me["code"]
        data = rows(c, "SELECT * FROM requests WHERE month=? AND (from_store=? OR to_store=?) ORDER BY date DESC, start_time DESC", (month, me, me))
    return {"requests": with_events(c, data)}


# ---- 月底核对 -------------------------------------------------------------
def close_info(c, month, code):
    mine = rows(c, "SELECT * FROM requests WHERE month=? AND (from_store=? OR to_store=?) ORDER BY date, start_time", (month, code, code))
    ap = [r for r in mine if r["status"] == "approved"]
    conf = one(c, "SELECT * FROM confirms WHERE month=? AND store=?", (month, code))
    sig = month_sig(c, month, code)
    inn = [r for r in ap if r["to_store"] == code]
    out = [r for r in ap if r["from_store"] == code]
    return {
        "month": month, "records": mine,
        "involved": any(r["status"] in LIVE for r in mine),
        "outHours": sum(tot_hours(r) for r in out),
        "inHours": sum(tot_hours(r) for r in inn),
        "opHours": sum((r["op_hours"] or 0) for r in ap), "nonHours": sum((r["non_hours"] or 0) for r in ap),
        "totHours": sum(tot_hours(r) for r in ap),
        "payNight": sum(r["night_pay"] or 0 for r in inn), "payLong": sum(r["long_pay"] or 0 for r in inn),
        "earnNight": sum(r["night_pay"] or 0 for r in out), "earnLong": sum(r["long_pay"] or 0 for r in out),
        "approved": len(ap),
        "pending": sum(1 for r in mine if r["status"] == "pending"),
        "disputed": sum(1 for r in mine if r["status"] == "disputed"),
        "adjusting": sum(1 for r in ap if r.get("adj_by")),
        "confirm": conf, "valid": bool(conf and conf["sig"] == sig),
    }


@route("GET", "/api/close", auth="store")
def api_close(req):
    info = close_info(req.conn, valid_month(req.q.get("month")), req.me["code"])
    with_events(req.conn, info["records"])
    return info


@route("POST", "/api/confirm", auth="store")
def api_confirm(req):
    month = valid_month(req.body.get("month"))
    manager = (req.body.get("manager") or "").strip()[:20]
    sigimg = req.body.get("signature") or ""
    me, c = req.me["code"], req.conn
    if not manager:
        raise ApiError("请填写店长姓名")
    if not sigimg.startswith("data:image/") or len(sigimg) > 400000:
        raise ApiError("签名图片无效或太大")
    with Tx(c):
        info = close_info(c, month, me)
        if info["pending"] or info["disputed"] or info["adjusting"]:
            raise ApiError("本月还有待确认、调整或疑义中的记录，处理完才能签名", 409)
        c.execute("INSERT OR REPLACE INTO confirms(month, store, manager, signature, signed_at, sig, count, out_hours, in_hours) VALUES(?,?,?,?,?,?,?,?,?)",
                  (month, me, manager, sigimg, now_ms(), month_sig(c, month, me), info["approved"], info["outHours"], info["inHours"]))
        pay = info["payNight"] + info["payLong"]
        write_log(c, req, "签名确认", "%s 店长 %s：调出 %g 小时、调入 %g 小时，共 %d 笔%s" % (
            month, manager, info["outHours"], info["inHours"], info["approved"], "；应付补贴 %g 元" % pay if pay else ""))
    return {"ok": True}


# ---- 人资：总览 -----------------------------------------------------------
def hq_codes(c):
    return [r["code"] for r in rows(c, "SELECT code FROM accounts WHERE role='hq'")]


def overview(c, month):
    live = rows(c, "SELECT * FROM requests WHERE month=? AND status IN ('pending','approved','disputed')", (month,))
    hqs = set(hq_codes(c))
    codes = sorted(set([r["from_store"] for r in live] + [r["to_store"] for r in live]) - hqs)
    stores = []
    for code in codes:
        info = close_info(c, month, code)
        conf = info["confirm"]
        stores.append({"code": code, "name": acc_name(c, code), "out": info["outHours"], "in": info["inHours"],
                       "pay": info["payNight"] + info["payLong"],
                       "approved": info["approved"], "pending": info["pending"], "disputed": info["disputed"], "adjusting": info["adjusting"],
                       "confirm": {k: conf[k] for k in ("manager", "signed_at")} if conf else None, "valid": info["valid"]})
    pend = sum(1 for r in live if r["status"] == "pending")
    disp = sum(1 for r in live if r["status"] == "disputed")
    adj = sum(1 for r in live if r["status"] == "approved" and r.get("adj_by"))
    done = sum(1 for s in stores if s["valid"])
    ready = bool(stores) and pend == 0 and disp == 0 and adj == 0 and done == len(stores)
    ap = [r for r in live if r["status"] == "approved"]
    return {"month": month, "stores": stores, "pending": pend, "disputed": disp, "adjusting": adj, "done": done, "ready": ready,
            "totalHours": sum(tot_hours(r) for r in ap), "opHours": sum(r["op_hours"] or 0 for r in ap), "nonHours": sum(r["non_hours"] or 0 for r in ap),
            "subsidy": sum((r["night_pay"] or 0) + (r["long_pay"] or 0) for r in ap), "special": sum(1 for r in ap if r["special"]),
            "approvedCount": len(ap)}


@route("GET", "/api/hr/home", auth="hr")
def api_hr_home(req):
    c = req.conn
    month = valid_month(req.q.get("month") or datetime.date.today().strftime("%Y-%m"))
    disputes = with_events(c, rows(c, "SELECT * FROM requests WHERE status='disputed' ORDER BY dispute_at"))
    hqs = hq_codes(c)
    hq_in, hq_adj = [], []
    if hqs:
        ph = ",".join("?" * len(hqs))
        hq_in = with_events(c, rows(c, "SELECT * FROM requests WHERE status='pending' AND counterparty IN (%s) ORDER BY date" % ph, hqs))
        hq_adj = with_events(c, rows(c, """SELECT * FROM requests WHERE status='approved' AND adj_by IS NOT NULL AND adj_by NOT IN (%s)
                                          AND (to_store IN (%s) OR from_store IN (%s)) ORDER BY date""" % (ph, ph, ph), hqs * 3))
    return {"disputes": disputes, "hqInbox": hq_in, "hqAdj": hq_adj, "overview": overview(c, month),
            "counts": {"stores": one(c, "SELECT COUNT(*) AS n FROM accounts WHERE role='store' AND active=1")["n"],
                       "staff": one(c, "SELECT COUNT(*) AS n FROM staff WHERE active=1")["n"],
                       "noProfile": sum(1 for a in rows(c, "SELECT code FROM accounts WHERE role='store' AND active=1") if not profile_complete(c, a["code"]))}}


@route("GET", "/api/hr/signature", auth="hr")
def api_hr_sig(req):
    r = one(req.conn, "SELECT * FROM confirms WHERE month=? AND store=?", (valid_month(req.q.get("month")), req.q.get("store")))
    if not r:
        raise ApiError("没有确认记录", 404)
    r["store_name"] = acc_name(req.conn, r["store"])
    return r


@route("POST", "/api/hr/unlock", auth="hr")
def api_hr_unlock(req):
    month, store = valid_month(req.body.get("month")), req.body.get("store")
    req.conn.execute("DELETE FROM confirms WHERE month=? AND store=?", (month, store))
    write_log(req.conn, req, "退回确认", "%s %s" % (month, acc_name(req.conn, store)))
    return {"ok": True}


@route("POST", "/api/hr/recalc", auth="hr")
def api_hr_recalc(req):
    c = req.conn
    month = valid_month(req.body.get("month"))
    cfg = rules.load_settings(c)
    changed = 0
    with Tx(c):
        for r in rows(c, "SELECT * FROM requests WHERE month=? AND status IN ('pending','approved','disputed')", (month,)):
            before = tuple(r[k] for k in rules.CALC_COLS) + (r["hours"],)
            x = apply_calc(c, r["id"], cfg)
            after = tuple(x[k] for k in rules.CALC_COLS) + (x["hours"],)
            if before != after:
                changed += 1
                add_event(c, r["id"], req.me["code"], "人资重新计算", "%g → %g 小时" % (tot_hours(r), x["op_hours"] + x["non_hours"]))
        write_log(c, req, "重新计算", "%s：%d 笔有变动" % (month, changed))
    return {"changed": changed}


# ---- 人资：设定与节假日 -----------------------------------------------------
SETTING_RULES = {"night_pay": "num", "long_pay": "num", "long_km": "num", "night_start": "time", "prep_min": "int", "clean_min": "int",
                 "hq_lunch_start": "time", "hq_lunch_end": "time", "amap_key": "text", "amap_sec": "text",
                 "amap_ws_key": "text", "dist_mode": "mode"}


@route("GET", "/api/hr/settings", auth="hr")
def api_hr_settings(req):
    c = req.conn
    st = rules.load_settings(c)
    out = {"settings": st, "holidays": rows(c, "SELECT * FROM holidays ORDER BY date")}
    if CFG.get("demo"):   # 演示版账号公开：金钥由正式版自动套用，不显示
        out["demoKeys"] = {k: bool(st.get(k)) for k in DEMO_KEY_FIELDS}
        for k in DEMO_KEY_FIELDS:
            st[k] = ""
    return out


DEMO_KEY_FIELDS = ("amap_key", "amap_sec", "amap_ws_key")


@route("POST", "/api/hr/settings", auth="hr")
def api_hr_settings_save(req):
    c, b = req.conn, req.body.get("settings") or {}
    if CFG.get("demo") and any(k in b for k in DEMO_KEY_FIELDS):
        raise ApiError("演示版的金钥由正式版自动套用，无法在这里修改")
    with Tx(c):
        for k, v in b.items():
            kind = SETTING_RULES.get(k)
            if not kind:
                continue
            v = str(v).strip()
            if kind in ("num", "int"):
                try:
                    f = float(v)
                except ValueError:
                    raise ApiError("「%s」须为数字" % k)
                if f < 0:
                    raise ApiError("「%s」不能为负数" % k)
                v = str(int(f)) if kind == "int" else ("%g" % f)
            elif kind == "time" and not re.match(r"^\d\d:\d\d$", v):
                raise ApiError("时间格式须为 HH:MM")
            elif kind == "mode" and v not in ("driving", "straight"):
                raise ApiError("距离计算方式不正确")
            if k in ("dist_mode", "amap_ws_key"):
                old = one(c, "SELECT value FROM settings WHERE key=?", (k,))
                if not old or old["value"] != v:   # 换了计算方式或金钥：清除自动计算的距离，下次重新取得
                    c.execute("DELETE FROM store_distances")
                    rules._FAIL["until"] = 0
            c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)", (k, v[:200]))
        write_log(c, req, "修改设定", "、".join(k for k in b if k in SETTING_RULES and not k.startswith("amap")) or "地图金钥")
    return {"ok": True}


@route("GET", "/api/hr/distances", auth="hr")
def api_hr_distances(req):
    """
    两店距离与长途判断清单。只列「有往来的两店」（有支援记录）+ 人资指定过的两店；
    all=1 时列出所有已定位门店两两组合。尚未计算的距离在这里计算（驾车会呼叫高德，单次最多 60 组）。
    """
    c = req.conn
    cfg = rules.load_settings(c)
    limit = float(cfg["long_km"])
    accs = {r["code"]: r for r in rows(c, "SELECT code, name, role, lat FROM accounts WHERE role IN ('store','hq')")}
    pairs = set()
    if req.q.get("all") == "1":
        located = sorted(k for k, v in accs.items() if v["lat"] is not None)
        pairs = {(x, y) for i, x in enumerate(located) for y in located[i + 1:]}
    else:
        for r in rows(c, "SELECT DISTINCT from_store, to_store FROM requests"):
            if r["from_store"] in accs and r["to_store"] in accs and r["from_store"] != r["to_store"]:
                pairs.add(rules.pair(r["from_store"], r["to_store"]))
    for r in rows(c, "SELECT a, b FROM long_overrides"):
        pairs.add((r["a"], r["b"]))
    out, errors, fetch_left = [], 0, 60
    for x, y in sorted(pairs):
        cached = one(c, "SELECT 1 AS k FROM store_distances WHERE a=? AND b=?", (x, y))
        d = None
        if cached or fetch_left > 0:
            if not cached:
                fetch_left -= 1
            d = rules.distance_info(c, x, y, cfg)
        ov = rules.long_override(c, x, y)
        if d and d.get("error"):
            errors += 1
        km = d["km"] if d else None
        auto = km is not None and km >= limit
        out.append({"a": x, "b": y, "an": accs.get(x, {}).get("name", x), "bn": accs.get(y, {}).get("name", y),
                    "km": km, "source": d["source"] if d else ("pending" if not cached and fetch_left <= 0 and accs[x]["lat"] is not None and accs[y]["lat"] is not None else None),
                    "error": (d or {}).get("error", ""), "auto": auto, "override": ov,
                    "isLong": ov if ov is not None else auto})
    out.sort(key=lambda p: (not p["isLong"], -(p["km"] or 0)))
    return {"pairs": out, "errors": errors, "mode": cfg["dist_mode"], "hasKey": bool(cfg["amap_ws_key"]), "limit": limit}


@route("POST", "/api/hr/distances", auth="hr")
def api_hr_distance_set(req):
    """人资指定两店是否长途：isLong = true / false / null(依距离自动)；refresh=true 重新取得距离。"""
    c, b = req.conn, req.body
    x, y = rules.pair(b.get("a") or "", b.get("b") or "")
    if x == y or not one(c, "SELECT 1 AS k FROM accounts WHERE code=?", (x,)) or not one(c, "SELECT 1 AS k FROM accounts WHERE code=?", (y,)):
        raise ApiError("门店不存在")
    label = "%s ↔ %s" % (acc_name(c, x), acc_name(c, y))
    if b.get("refresh"):
        c.execute("DELETE FROM store_distances WHERE a=? AND b=?", (x, y))
        rules._FAIL["until"] = 0
        d = rules.distance_info(c, x, y)
        write_log(c, req, "重新取得距离", label)
        return {"ok": True, "km": d["km"] if d else None, "source": d["source"] if d else None, "error": (d or {}).get("error", "")}
    v = b.get("isLong")
    if v is None:
        c.execute("DELETE FROM long_overrides WHERE a=? AND b=?", (x, y))
        write_log(c, req, "长途改回自动判断", label)
    else:
        c.execute("INSERT OR REPLACE INTO long_overrides(a, b, is_long, updated_by, updated_at) VALUES(?,?,?,?,?)",
                  (x, y, 1 if v else 0, req.me["code"], now_ms()))
        write_log(c, req, "指定长途", "%s：%s" % (label, "长途" if v else "非长途"))
    return {"ok": True}


@route("POST", "/api/hr/holidays", auth="hr")
def api_hr_holidays(req):
    c, b = req.conn, req.body
    d = b.get("date") or ""
    try:
        datetime.date.fromisoformat(d)
    except ValueError:
        raise ApiError("日期不正确")
    if b.get("delete"):
        c.execute("DELETE FROM holidays WHERE date=?", (d,))
        write_log(c, req, "删除三倍薪日", d)
    else:
        name = (b.get("name") or "").strip()[:20] or "法定节假日"
        c.execute("INSERT OR REPLACE INTO holidays(date, name) VALUES(?,?)", (d, name))
        write_log(c, req, "新增三倍薪日", "%s %s" % (d, name))
    return {"ok": True}


# ---- 导出 -------------------------------------------------------------------
def build_detail(recs, c):
    """依实际发生的项目决定栏位（没有夜班就不出现夜班栏位）。"""
    with_events(c, recs)
    recs = sorted(recs, key=lambda x: (x["date"], x["start_time"]))
    has = lambda f: any(f(r) for r in recs)
    cols = [("日期", 11, lambda r: r["date"]), ("伙伴", 8, lambda r: r["staff_name"]), ("工号", 8, lambda r: r["staff_emp_no"] or ""),
            ("原属门店编号", 12, lambda r: r["from_store"]), ("原属门店", 14, lambda r: acc_name(c, r["from_store"])),
            ("支援门店编号", 12, lambda r: r["to_store"]), ("支援门店", 14, lambda r: acc_name(c, r["to_store"])),
            ("开始", 7, lambda r: r["start_time"]), ("结束", 10, lambda r: rules.tlabel(rules.tmin(r["end_time"])))]
    cols.append(("性质", 8, lambda r: "非营运" if r["nature"] == "non" else "营运"))
    if has(lambda r: r["special"]):
        cols.append(("特殊状况/项目", 12, lambda r: r["special"] or ""))
    if has(lambda r: r["holiday"]):
        cols.append(("三倍薪日", 12, lambda r: r["holiday"] or ""))
    cols.append(("营运工时", 9, lambda r: r["op_hours"] if r["op_hours"] is not None else r["hours"]))
    if has(lambda r: r["non_hours"]):
        cols.append(("非营运工时", 10, lambda r: r["non_hours"] or 0))
    cols.append(("合计工时", 9, lambda r: tot_hours(r)))
    if has(lambda r: r["night_pay"]):
        cols += [("夜班时数", 9, lambda r: r["night_hours"] or ""), ("夜班补贴", 9, lambda r: r["night_pay"] or "")]
    if has(lambda r: r["long_pay"]):
        cols += [("直线距离(公里)", 13, lambda r: r["long_km"] if r["long_pay"] else ""), ("长途补贴", 9, lambda r: r["long_pay"] or "")]
    if has(lambda r: (r["night_pay"] or 0) + (r["long_pay"] or 0)):
        cols += [("补贴合计", 9, lambda r: ((r["night_pay"] or 0) + (r["long_pay"] or 0)) or ""),
                 ("承担门店", 14, lambda r: acc_name(c, r["payer"] or r["to_store"]) if (r["night_pay"] or 0) + (r["long_pay"] or 0) else "")]
    cols += [("原因", 12, lambda r: r["reason"]), ("备注", 16, lambda r: r["note"] or ""), ("发起门店", 14, lambda r: acc_name(c, r["initiator"])),
             ("对方确认时间", 16, lambda r: fmt_ts(r["decided_at"]))]
    adj = lambda r: "；".join("%s（%s）" % (e["note"], acc_name(c, e["who"])) for e in r["events"] if e["act"] == "同意工时调整")
    if has(adj):
        cols.append(("调整记录", 34, adj))
    out = [[h for h, w, f in cols]] + [[f(r) for h, w, f in cols] for r in recs]
    return out, [w for h, w, f in cols]


def xlsx_response(name, sheets):
    return {"__file__": xlsx.write(sheets), "filename": name + ".xlsx",
            "type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


@route("GET", "/api/hr/export", auth="hr")
def api_hr_export(req):
    c = req.conn
    month = valid_month(req.q.get("month"))
    ov = overview(c, month)
    force = req.q.get("force") == "1"
    if not ov["ready"] and not force:
        raise ApiError("本月尚未全部核对完成", 409)
    ap = rows(c, "SELECT * FROM requests WHERE month=? AND status='approved'", (month,))
    any_non = any(r["non_hours"] for r in ap)
    any_sub = any((r["night_pay"] or 0) + (r["long_pay"] or 0) for r in ap)
    # 门店汇总（含总部）
    codes = sorted(set([r["from_store"] for r in ap] + [r["to_store"] for r in ap]))
    head = ["门店编号", "门店", "调出合计工时", "调入合计工时", "调入·营运工时"] + (["调入·非营运工时"] if any_non else []) + \
           (["应付夜班补贴", "应付长途补贴", "应付补贴合计"] if any_sub else []) + ["确认店长", "确认时间", "状态"]
    st = {s["code"]: s for s in ov["stores"]}
    stores = [head]
    for code in codes:
        o = [r for r in ap if r["from_store"] == code]
        i = [r for r in ap if r["to_store"] == code]
        s = st.get(code)
        row = [code, acc_name(c, code), sum(tot_hours(r) for r in o), sum(tot_hours(r) for r in i), sum(r["op_hours"] or 0 for r in i)]
        if any_non:
            row.append(sum(r["non_hours"] or 0 for r in i))
        if any_sub:
            pn, pl = sum(r["night_pay"] or 0 for r in i), sum(r["long_pay"] or 0 for r in i)
            row += [pn, pl, pn + pl]
        row += [((s or {}).get("confirm") or {}).get("manager", ""), fmt_ts(((s or {}).get("confirm") or {}).get("signed_at")),
                ("已确认" if s["valid"] else ("确认后有变动" if s["confirm"] else "未确认")) if s else "总部（不需签名）"]
        stores.append(row)
    # 伙伴汇总
    per = {}
    for r in ap:
        k = r["staff_id"]
        p = per.setdefault(k, {"name": r["staff_name"], "emp": r["staff_emp_no"] or "", "store": acc_name(c, r["from_store"]),
                               "n": 0, "op": 0.0, "non": 0.0, "tot": 0.0, "night": 0.0, "long": 0.0})
        p["n"] += 1
        p["op"] += r["op_hours"] or 0
        p["non"] += r["non_hours"] or 0
        p["tot"] += tot_hours(r)
        p["night"] += r["night_pay"] or 0
        p["long"] += r["long_pay"] or 0
    ph = ["伙伴", "工号", "原属门店", "支援次数", "营运工时"] + (["非营运工时"] if any_non else []) + ["合计工时"] + \
         (["夜班补贴", "长途补贴", "应得补贴合计"] if any_sub else [])
    staff = [ph]
    for p in sorted(per.values(), key=lambda x: -x["tot"]):
        row = [p["name"], p["emp"], p["store"], p["n"], p["op"]] + ([p["non"]] if any_non else []) + [p["tot"]]
        if any_sub:
            row += [p["night"], p["long"], p["night"] + p["long"]]
        staff.append(row)
    canc = [["日期", "伙伴", "原属门店", "支援门店", "工时", "疑义提出门店", "疑义原因", "人资说明"]]
    for r in with_events(c, rows(c, "SELECT * FROM requests WHERE month=? AND status='cancelled'", (month,))):
        last = r["events"][-1] if r["events"] else {}
        canc.append([r["date"], r["staff_name"], acc_name(c, r["from_store"]), acc_name(c, r["to_store"]), tot_hours(r),
                     acc_name(c, r["dispute_by"] or ""), r["dispute_note"] or "", last.get("note", "")])
    detail, widths = build_detail(ap, c)
    sheets = [("支援明细", detail, widths), ("门店汇总", stores, [10, 14] + [13] * (len(head) - 2)),
              ("伙伴汇总", staff, [10, 10, 14] + [11] * (len(ph) - 3))]
    if any(r["out_of_hours"] for r in ap):
        sp_rows, sw = build_detail([r for r in ap if r["out_of_hours"]], c)
        sheets.append(("超出营业时间", sp_rows, sw))
    sheets.append(("已取消记录", canc, [11, 8, 14, 14, 6, 14, 24, 24]))
    write_log(c, req, "导出月结", "%s%s" % (month, "（未完成核对，预览）" if not ov["ready"] else ""))
    return xlsx_response("跨店支援工时_%s%s" % (month, "" if ov["ready"] else "_预览"), sheets)


@route("GET", "/api/export/store", auth="store")
def api_store_export(req):
    c, me = req.conn, req.me["code"]
    month = valid_month(req.q.get("month"))
    ap = rows(c, "SELECT * FROM requests WHERE month=? AND status='approved' AND (from_store=? OR to_store=?)", (month, me, me))
    write_log(c, req, "导出本店明细", month)
    detail, widths = build_detail(ap, c)
    return xlsx_response("跨店支援_%s_%s" % (req.me["name"], month), [("本店支援明细", detail, widths)])


# ---- 人资：账号与人员 -------------------------------------------------------
@route("POST", "/api/hr/accounts", auth="hr")
def api_hr_acc_save(req):
    b, c = req.body, req.conn
    code = (b.get("code") or "").strip()
    name = (b.get("name") or "").strip()[:40]
    role = b.get("role") if b.get("role") in ("hr", "hq") else "store"
    phone = re.sub(r"[\s-]", "", str(b.get("phone") or ""))[:20]
    active = 1 if b.get("active", True) else 0
    if not CODE_RE.match(code):
        raise ApiError("编号只能用英文字母、数字、-、_")
    if not name:
        raise ApiError("请填写名称")
    with Tx(c):
        ex = one(c, "SELECT * FROM accounts WHERE code=? COLLATE NOCASE", (code,))
        if b.get("isNew") and ex:
            raise ApiError("该编号已存在")
        if ex and ex["code"] == req.me["code"] and (not active or role != "hr"):
            raise ApiError("不能停用或降级当前登录的人资账号")
        if ex:
            c.execute("UPDATE accounts SET name=?, role=?, phone=?, active=?, updated_at=? WHERE code=?", (name, role, phone, active, now_ms(), ex["code"]))
            if not active:
                c.execute("DELETE FROM sessions WHERE code=?", (ex["code"],))
            write_log(c, req, "修改账号", "%s %s%s" % (ex["code"], name, "（停用）" if not active else ""))
        else:
            c.execute("INSERT INTO accounts(code, name, role, phone, active, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
                      (code, name, role, phone, active, now_ms(), now_ms()))
            write_log(c, req, "新增账号", "%s %s" % (code, name))
    return {"ok": True}


@route("POST", "/api/hr/staff", auth="hr")
def api_hr_staff_save(req):
    b, c = req.body, req.conn
    sid = b.get("id")
    store = (b.get("store") or "").strip()
    name = (b.get("name") or "").strip()[:20]
    emp = (b.get("empNo") or "").strip()[:20]
    active = 1 if b.get("active", True) else 0
    if not one(c, "SELECT 1 AS x FROM accounts WHERE code=? AND role='store'", (store,)):
        raise ApiError("请选择门店")
    if not name:
        raise ApiError("请填写姓名")
    with Tx(c):
        if emp:
            dup = one(c, "SELECT * FROM staff WHERE emp_no=? AND id<>?", (emp, int(sid or 0)))
            if dup:
                raise ApiError("工号 %s 已被 %s 使用" % (emp, dup["name"]))
        if sid:
            c.execute("UPDATE staff SET store=?, name=?, emp_no=?, active=?, updated_at=? WHERE id=?", (store, name, emp, active, now_ms(), int(sid)))
            write_log(c, req, "修改人员", "%s（%s）%s" % (name, acc_name(c, store), "离职" if not active else ""))
        else:
            if one(c, "SELECT 1 AS x FROM staff WHERE store=? AND name=? AND emp_no=?", (store, name, emp)):
                raise ApiError("该门店已有同名人员")
            c.execute("INSERT INTO staff(store, name, emp_no, active, created_at, updated_at) VALUES(?,?,?,?,?,?)", (store, name, emp, active, now_ms(), now_ms()))
            write_log(c, req, "新增人员", "%s（%s）" % (name, acc_name(c, store)))
    return {"ok": True}


# ---- 人资：批量导入 ---------------------------------------------------------
IMPORT_SPEC = {
    "store": {"cols": ["code", "name", "phone"],
              "spec": [("code", ["门店编号", "编号", "账号", "门店代码", "门店账号"]),
                       ("phone", ["门店手机号", "手机号", "手机", "电话", "联系电话"]),
                       ("name", ["门店名称", "名称", "店名", "门店"])],
              "template": [["门店编号", "门店名称", "门店手机号"], ["TJ001", "南开大悦城店", "13800000001"], ["TJ002", "和平滨江道店", "13800000002"]]},
    "staff": {"cols": ["store", "name", "empNo"],
              "spec": [("empNo", ["工号", "伙伴编号", "伙伴工号", "员工编号", "员工工号"]),
                       ("store", ["门店编号", "门店代码", "所属门店", "门店名称", "门店"]),
                       ("name", ["姓名", "伙伴姓名", "伙伴", "名字", "员工姓名", "员工"])],
              "template": [["门店编号", "姓名", "工号"], ["TJ001", "张小美", "A1023"], ["TJ001", "李大明", ""], ["TJ002", "王芳", "A2001"]]},
}


def map_rows(raw, kind):
    sp = IMPORT_SPEC[kind]
    raw = [[str(x or "").strip() for x in r] for r in raw]
    raw = [r for r in raw if any(r)]
    if not raw:
        return []
    head = [re.sub(r"\s", "", h) for h in raw[0]]
    idx, used, is_head = {}, set(), False
    for key, names in sp["spec"]:
        i = next((j for j, h in enumerate(head) if j not in used and h in names), -1)
        if i < 0:
            i = next((j for j, h in enumerate(head) if j not in used and h and any(n in h for n in names)), -1)
        if i >= 0:
            idx[key] = i
            used.add(i)
            is_head = True
    if not is_head:
        idx = {k: i for i, k in enumerate(sp["cols"])}
    out = []
    for n, r in enumerate(raw[1 if is_head else 0:]):
        o = {"line": n + (2 if is_head else 1)}
        for k in sp["cols"]:
            o[k] = r[idx[k]] if k in idx and idx[k] < len(r) else ""
        out.append(o)
    return out


def plan_import(c, kind, items):
    plan, seen = [], set()
    if kind == "store":
        for r in items:
            r["phone"] = re.sub(r"[\s-]", "", r["phone"])[:20]
            code = r["code"]
            ex = one(c, "SELECT * FROM accounts WHERE code=? COLLATE NOCASE", (code,))
            if not CODE_RE.match(code):
                plan.append(dict(r=r, st="error", msg="门店编号格式不正确（只能用字母、数字、-、_）")); continue
            if code.lower() in seen:
                plan.append(dict(r=r, st="error", msg="文件内编号重复")); continue
            seen.add(code.lower())
            if ex and ex["role"] == "hr":
                plan.append(dict(r=r, st="error", msg="与人资账号重复")); continue
            if not ex:
                if not r["name"]:
                    plan.append(dict(r=r, st="error", msg="缺少门店名称")); continue
                plan.append(dict(r=r, st="new", msg=""))
                continue
            ch = []
            if r["name"] and r["name"] != ex["name"]:
                ch.append("名称：%s → %s" % (ex["name"], r["name"]))
            if r["phone"] and r["phone"] != ex["phone"]:
                ch.append("电话更新")
            if not ex["active"]:
                ch.append("重新启用")
            plan.append(dict(r=r, st="update" if ch else "same", msg="；".join(ch) or "资料相同", code=ex["code"]))
    else:
        for r in items:
            sv = r["store"]
            acc = one(c, "SELECT * FROM accounts WHERE role='store' AND (code=? COLLATE NOCASE OR name=?)", (sv, sv))
            if not acc:
                plan.append(dict(r=r, st="error", msg="找不到门店「%s」，请先建立门店账号" % (sv or "空白"))); continue
            store = acc["code"]
            if not r["name"]:
                plan.append(dict(r=r, st="error", msg="缺少姓名")); continue
            key = "#" + r["empNo"] if r["empNo"] else store + "|" + r["name"]
            if key in seen:
                plan.append(dict(r=r, st="error", msg="文件内重复")); continue
            seen.add(key)
            ex = one(c, "SELECT * FROM staff WHERE emp_no=?", (r["empNo"],)) if r["empNo"] else None
            if not ex:
                ex = one(c, "SELECT * FROM staff WHERE store=? AND name=?", (store, r["name"]))
            if not ex:
                plan.append(dict(r=r, st="new", msg="", store=store)); continue
            ch = []
            if ex["store"] != store:
                ch.append("调店：%s → %s" % (acc_name(c, ex["store"]), acc["name"]))
            if ex["name"] != r["name"]:
                ch.append("姓名：%s → %s" % (ex["name"], r["name"]))
            if r["empNo"] and ex["emp_no"] != r["empNo"]:
                ch.append("工号：%s" % r["empNo"])
            if not ex["active"]:
                ch.append("恢复在职")
            plan.append(dict(r=r, st="update" if ch else "same", msg="；".join(ch) or "已在清单中", store=store, id=ex["id"]))
    return plan


@route("POST", "/api/hr/import", auth="hr")
def api_hr_import(req):
    b, c = req.body, req.conn
    kind = b.get("kind")
    if kind not in IMPORT_SPEC:
        raise ApiError("类型错误")
    if b.get("file"):
        data = base64.b64decode(b["file"].get("data") or "")
        fname = (b["file"].get("name") or "").lower()
        raw = xlsx.read_csv(data) if fname.endswith((".csv", ".txt")) else xlsx.read_xlsx(data)
    else:
        raw = xlsx.read_text(b.get("text") or "")
    items = map_rows(raw, kind)
    if len(items) > 3000:
        raise ApiError("一次最多导入 3000 行")
    if not b.get("apply"):
        plan = plan_import(c, kind, items)
        return {"plan": [{"line": p["r"]["line"], "data": p["r"], "st": p["st"], "msg": p["msg"]} for p in plan]}
    n_new = n_upd = 0
    with Tx(c):
        plan = plan_import(c, kind, items)
        t = now_ms()
        for p in plan:
            r = p["r"]
            if kind == "store":
                if p["st"] == "new":
                    c.execute("INSERT INTO accounts(code, name, role, phone, active, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
                              (r["code"], r["name"], "store", r["phone"], 1, t, t)); n_new += 1
                elif p["st"] == "update":
                    ex = one(c, "SELECT * FROM accounts WHERE code=?", (p["code"],))
                    c.execute("UPDATE accounts SET name=?, phone=?, active=1, updated_at=? WHERE code=?",
                              (r["name"] or ex["name"], r["phone"] or ex["phone"], t, p["code"])); n_upd += 1
            else:
                if p["st"] == "new":
                    c.execute("INSERT INTO staff(store, name, emp_no, active, created_at, updated_at) VALUES(?,?,?,?,?,?)",
                              (p["store"], r["name"], r["empNo"], 1, t, t)); n_new += 1
                elif p["st"] == "update":
                    ex = one(c, "SELECT * FROM staff WHERE id=?", (p["id"],))
                    c.execute("UPDATE staff SET store=?, name=?, emp_no=?, active=1, updated_at=? WHERE id=?",
                              (p["store"], r["name"], r["empNo"] or ex["emp_no"], t, p["id"])); n_upd += 1
        write_log(c, req, "导入门店" if kind == "store" else "导入人员", "新增 %d、更新 %d、略过 %d" % (n_new, n_upd, len(plan) - n_new - n_upd))
    return {"new": n_new, "updated": n_upd}


@route("GET", "/api/hr/template", auth="hr")
def api_hr_template(req):
    kind = req.q.get("kind")
    if kind not in IMPORT_SPEC:
        raise ApiError("类型错误")
    return xlsx_response("门店账号导入模板" if kind == "store" else "人员清单导入模板",
                         [("导入", IMPORT_SPEC[kind]["template"], [16, 18, 16])])


# ---- 人资：操作日志 ---------------------------------------------------------
def log_query(req):
    q = req.q
    where, args = [], []
    try:
        d1 = datetime.datetime.strptime(q.get("from") or "", "%Y-%m-%d")
    except ValueError:
        d1 = datetime.datetime.combine(datetime.date.today() - datetime.timedelta(days=6), datetime.time())
    try:
        d2 = datetime.datetime.strptime(q.get("to") or "", "%Y-%m-%d")
    except ValueError:
        d2 = datetime.datetime.combine(datetime.date.today(), datetime.time())
    where.append("t >= ? AND t < ?")
    args += [int(d1.timestamp() * 1000), int((d2 + datetime.timedelta(days=1)).timestamp() * 1000)]
    if q.get("code"):
        where.append("code = ? COLLATE NOCASE"); args.append(q["code"])
    if q.get("action"):
        where.append("action = ?"); args.append(q["action"])
    if q.get("q"):
        where.append("(detail LIKE ? OR ip LIKE ? OR device LIKE ?)"); args += ["%" + q["q"] + "%"] * 3
    return " AND ".join(where), args


@route("GET", "/api/hr/logs", auth="hr")
def api_hr_logs(req):
    w, a = log_query(req)
    limit = min(int(req.q.get("limit") or 200), 1000)
    offset = int(req.q.get("offset") or 0)
    data = rows(req.conn, "SELECT id, t, code, role, action, detail, ip, device FROM logs WHERE %s ORDER BY t DESC LIMIT ? OFFSET ?" % w, a + [limit, offset])
    total = one(req.conn, "SELECT COUNT(*) AS n FROM logs WHERE %s" % w, a)["n"]
    actions = [r["action"] for r in rows(req.conn, "SELECT DISTINCT action FROM logs ORDER BY action")]
    oldest = one(req.conn, "SELECT MIN(t) AS t FROM logs")["t"]
    return {"logs": data, "total": total, "actions": actions, "retentionDays": CFG["log_retention_days"], "oldest": oldest}


@route("GET", "/api/hr/logs/export", auth="hr")
def api_hr_logs_export(req):
    w, a = log_query(req)
    data = rows(req.conn, "SELECT * FROM logs WHERE %s ORDER BY t DESC LIMIT 50000" % w, a)
    out = [["时间", "账号", "名称", "角色", "操作", "内容", "IP", "装置", "User-Agent"]]
    names = {r["code"]: r["name"] for r in rows(req.conn, "SELECT code, name FROM accounts")}
    for r in data:
        out.append([fmt_ts(r["t"]), r["code"], names.get(r["code"], ""), {"hr": "人资", "store": "门店"}.get(r["role"], ""), r["action"],
                    r["detail"], r["ip"], r["device"], r["ua"]])
    write_log(req.conn, req, "导出日志", "%d 笔" % len(data))
    return xlsx_response("操作日志_%s" % datetime.date.today().isoformat(), [("操作日志", out, [17, 10, 14, 6, 12, 50, 16, 28, 50])])


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "YDD-Support/" + APP_VERSION
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # 不在主控台刷屏；操作记录写入 logs 表

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def client_ip(self):
        if CFG.get("trust_proxy"):
            xf = self.headers.get("X-Forwarded-For") or self.headers.get("X-Real-IP")
            if xf:
                return xf.split(",")[0].strip()[:45]
        return self.client_address[0]

    def send(self, status, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def static(self, path):
        if path in ("/", "/index.html"):
            fp = os.path.join(HERE, "static", "index.html")
            with open(fp, "rb") as f:
                return self.send(200, f.read(), "text/html; charset=utf-8")
        if path == "/healthz":
            return self.send(200, {"ok": True, "version": APP_VERSION})
        return self.send(404, {"error": "not found"})

    def dispatch(self, method):
        u = urlparse(self.path)
        if not u.path.startswith("/api/"):
            return self.static(u.path)
        req = Req()
        req.q = {k: v[0] for k, v in parse_qs(u.query).items()}
        req.ip = self.client_ip()
        req.ua = self.headers.get("User-Agent", "")
        req.device = parse_device(req.ua, self.headers.get("X-Device-Model", ""))
        req.body = {}
        req.me = None
        req.token = None
        if method == "POST":
            n = int(self.headers.get("Content-Length") or 0)
            if n > 12 * 1024 * 1024:
                return self.send(413, {"error": "资料太大"})
            raw = self.rfile.read(n) if n else b""
            try:
                req.body = json.loads(raw.decode("utf-8")) if raw else {}
            except ValueError:
                return self.send(400, {"error": "格式错误"})
        conn = db.connect(DB_PATH)
        req.conn = conn
        try:
            for m, rx, auth, fn in ROUTES:
                if m != method:
                    continue
                mt = rx.match(u.path)
                if not mt:
                    continue
                req.args = mt.groups()
                if auth:
                    tok = (self.headers.get("Authorization") or "").replace("Bearer ", "").strip()
                    s = one(conn, "SELECT s.*, a.name, a.role, a.active FROM sessions s JOIN accounts a ON a.code=s.code WHERE s.token=?", (tok,)) if tok else None
                    if not s or not s["active"] or s["last_seen"] < now_ms() - CFG["session_days"] * 86400000:
                        raise ApiError("请重新登录", 401)
                    if auth in ("store", "hr") and s["role"] != auth:
                        raise ApiError("无权使用此功能", 403)
                    req.token = tok
                    req.me = {"code": s["code"], "name": s["name"], "role": s["role"]}
                    if now_ms() - s["last_seen"] > 600000:
                        conn.execute("UPDATE sessions SET last_seen=?, ip=?, device=? WHERE token=?", (now_ms(), req.ip, req.device, tok))
                res = fn(req)
                if isinstance(res, dict) and "__file__" in res:
                    fn_q = quote(res["filename"])
                    return self.send(200, res["__file__"], res["type"],
                                     {"Content-Disposition": "attachment; filename=\"export.xlsx\"; filename*=UTF-8''%s" % fn_q})
                return self.send(200, res)
            return self.send(404, {"error": "找不到功能"})
        except ApiError as e:
            return self.send(e.status, {"error": str(e)})
        except Exception:
            traceback.print_exc()
            return self.send(500, {"error": "服务器错误，请稍后重试"})
        finally:
            conn.close()


# ---------------------------------------------------------------- 背景维护
def cleanup_once():
    """删除超过保留天数的操作日志与过期登录会话。回传删除的日志笔数。"""
    conn = db.connect(DB_PATH)
    try:
        cutoff = now_ms() - int(CFG["log_retention_days"]) * 86400000
        n = conn.execute("DELETE FROM logs WHERE t < ?", (cutoff,)).rowcount
        if n:
            conn.execute("INSERT INTO logs(t, code, role, action, detail, ip, device, ua) VALUES(?,?,?,?,?,?,?,?)",
                         (now_ms(), "系统", "", "清理日志", "删除 %d 天前的日志 %d 笔" % (CFG["log_retention_days"], n), "", "", ""))
        conn.execute("DELETE FROM sessions WHERE last_seen < ?", (now_ms() - CFG["session_days"] * 86400000,))
        return n
    finally:
        conn.close()


def maintenance_loop():
    last_backup_day = None
    while True:
        try:
            cleanup_once()
            today = datetime.date.today()
            if CFG.get("daily_backup") and last_backup_day != today:
                db.backup(DB_PATH, tag="daily", keep=int(CFG.get("backup_keep", 30)))
                last_backup_day = today
        except Exception:
            traceback.print_exc()
        time.sleep(6 * 3600)


def main():
    before, after = db.migrate(DB_PATH)
    if before != after:
        print("资料库已升级：v%d → v%d" % (before, after))
    t = threading.Thread(target=maintenance_loop, daemon=True)
    t.start()
    srv = ThreadingHTTPServer((CFG["host"], int(CFG["port"])), Handler)
    srv.daemon_threads = True
    print("1点点 跨店支援工时系统 v%s 已启动%s" % (APP_VERSION, "（演示版）" if CFG.get("demo") else ""))
    print("资料库：%s（结构版本 v%d）" % (DB_PATH, after))
    print("电脑浏览器打开：http://localhost:%s" % CFG["port"])
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        print("同一 Wi-Fi 的手机打开：http://%s:%s" % (s.getsockname()[0], CFG["port"]))
        s.close()
    except Exception:
        pass
    print("按 Ctrl+C 停止服务")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")


if __name__ == "__main__":
    main()
