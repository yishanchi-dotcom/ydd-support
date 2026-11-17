#!/usr/bin/env python3
"""
演示版资料：清空本目录资料库，建立示范门店、伙伴与各种状态的支援记录（日期落在本月）。
只用在演示版目录（config.json 里 "demo": true），正式版执行会被拒绝。
用法：先停止演示服务，再执行  python3 demo_seed.py
"""
import os
import sys
import json
import time
import calendar
import datetime
import threading
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import server  # noqa: E402  读取本目录 config.json
import db      # noqa: E402

if not server.CFG.get("demo"):
    sys.exit("这不是演示版目录（config.json 没有 \"demo\": true），已停止，不会动到资料。")

for ext in ("", "-wal", "-shm"):
    if os.path.exists(server.DB_PATH + ext):
        os.remove(server.DB_PATH + ext)
os.makedirs(os.path.dirname(server.DB_PATH), exist_ok=True)
db.migrate(server.DB_PATH, do_backup=False)

# 从正式版复制高德金钥（只读开启正式版资料库，不会改动它）
KEYS = ("amap_key", "amap_sec", "amap_ws_key", "dist_mode")
src = server.CFG.get("demo_keys_from") or ""
copied = []
if src and os.path.exists(src) and os.path.abspath(src) != os.path.abspath(server.DB_PATH):
    import sqlite3
    try:
        ro = sqlite3.connect("file:%s?mode=ro" % src, uri=True)
        vals = dict(ro.execute("SELECT key, value FROM settings WHERE key IN (%s)" % ",".join("?" * len(KEYS)), KEYS).fetchall())
        ro.close()
        w = sqlite3.connect(server.DB_PATH)
        for k, v in vals.items():
            if v:
                w.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)", (k, v))
                copied.append(k)
        w.commit()
        w.close()
    except Exception as e:
        print("读取正式版金钥失败（演示版改用直线距离、无地图）：%s" % e)

srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
B = "http://127.0.0.1:%d" % srv.server_address[1]


def call(path, body=None, tok=None):
    h = {"Content-Type": "application/json", "User-Agent": "demo-seed"}
    if tok:
        h["Authorization"] = "Bearer " + tok
    req = urllib.request.Request(B + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers=h, method="POST" if body is not None else "GET")
    try:
        return json.loads(urllib.request.urlopen(req).read())
    except urllib.error.HTTPError as e:
        raise SystemExit("示范资料建立失败：%s %s → %s" % (path, body, e.read().decode()))


today = datetime.date.today()
last = calendar.monthrange(today.year, today.month)[1]
def D(day):
    return datetime.date(today.year, today.month, min(day, last)).isoformat()

hr = call("/api/setup", {"code": "HR", "name": "人资部"})["token"]
call("/api/hr/import", {"kind": "store", "apply": True, "text": "\n".join([
    "TJ001\t和平大悦城店", "TJ002\t南开大悦城店", "TJ005\t奥城店", "TJ007\t天河城店", "TJ009\t于家堡店", "TJ010\t新开店（示范首次登录）"])}, hr)
call("/api/hr/accounts", {"code": "HQ", "name": "总部", "role": "hq", "isNew": True}, hr)
call("/api/hr/import", {"kind": "staff", "apply": True, "text": "\n".join([
    "TJ001\t小明\tA101", "TJ001\t小美\tA102", "TJ002\t阿杰\tB201", "TJ002\t小芳\tB202",
    "TJ005\t小林\tC501", "TJ005\t小雨\tC502", "TJ007\t小王\tD701", "TJ009\t小华\tE901"])}, hr)

DAILY = [{"days": [], "open": "10:00", "close": "22:00"}]
PROFILES = {
    "TJ001": ("天津市和平区南京路 和平大悦城", 39.1255, 117.1950, DAILY),
    "TJ002": ("天津市南开区南门外大街 南开大悦城", 39.1390, 117.1630, DAILY),
    "TJ005": ("天津市南开区奥城商业广场", 39.0950, 117.1580,
              [{"days": [], "open": "10:00", "close": "24:00"}, {"days": [5, 6, 7], "open": "10:00", "close": "25:00"}]),
    "TJ007": ("天津市河西区天河城", 39.1180, 117.2090, DAILY),
    "TJ009": ("天津市滨海新区于家堡", 39.0080, 117.7010, DAILY),
    "HQ":    ("天津市河西区友谊路（总部）", 39.1100, 117.2150, None),
}
for code, (addr, lat, lng, hours) in PROFILES.items():
    body = {"store": code, "address": addr, "lat": lat, "lng": lng}
    if hours:
        body["hours"] = hours
    call("/api/store/profile", body, hr)

HOLI = D(13)
call("/api/hr/holidays", {"date": HOLI, "name": "示范用节假日"}, hr)

tok = {c: call("/api/login", {"code": c})["token"] for c in ("TJ001", "TJ002", "TJ005", "TJ007", "TJ009")}
staff = {}
for c in tok:
    for s in call("/api/staff?store=" + c, tok=tok[c])["staff"]:
        staff[s["name"]] = s["id"]


def new(by, kind, store, who, day, st, en, reason="人手不足", special=""):
    b = {"kind": kind, "store": store, "staffIds": [staff[who]], "date": D(day), "start": st, "end": en, "reason": reason}
    if special:
        b["special"] = special
    return call("/api/requests", b, tok[by])["created"][0]


def act(rid, action, who_tok, **kw):
    return call("/api/requests/%d/%s" % (rid, action), kw, who_tok)

# 已归档：夜班
r = new("TJ001", "out", "TJ005", "小明", 2, "18:00", "24:30"); act(r, "approve", tok["TJ005"])
# 已归档：长途
r = new("TJ001", "out", "TJ009", "小美", 4, "13:00", "18:00"); act(r, "approve", tok["TJ009"])
# 已归档：调入
r = new("TJ002", "in", "TJ001", "小明", 6, "10:00", "18:00", "促销活动"); act(r, "approve", tok["TJ001"])
# 已归档：总部开会（人资同意）
r = new("TJ001", "out", "HQ", "小美", 9, "09:00", "18:00", "培训带教"); act(r, "approve", hr)
# 已归档：超出营业时间 → 大扫除（非营运）
r = new("TJ007", "out", "TJ005", "小王", 11, "07:00", "12:00", special="大扫除"); act(r, "approve", tok["TJ005"])
# 已归档：节假日三倍薪
r = new("TJ005", "out", "TJ007", "小林", 13, "10:00", "18:00"); act(r, "approve", tok["TJ007"])
# 已归档 + 工时调整待确认（南开大悦城店会看到弹窗）
r = new("TJ002", "out", "TJ001", "阿杰", 16, "14:00", "20:00"); act(r, "approve", tok["TJ001"])
act(r, "adjust", tok["TJ001"], start="14:00", end="19:00", note="当天提早一小时结束")
# 已归档 + 疑义（人资首页会看到）
r = new("TJ005", "out", "TJ002", "小雨", 6, "12:00", "20:00"); act(r, "approve", tok["TJ002"])
act(r, "dispute", tok["TJ002"], note="当天伙伴实际没有到店，请人资确认")
# 已驳回
r = new("TJ009", "out", "TJ001", "小华", 20, "10:00", "16:00"); act(r, "reject", tok["TJ001"], note="当天人手已足够")
# 待确认（奥城店、天河城店登录会看到弹窗）
new("TJ001", "out", "TJ005", "小美", 18, "12:00", "18:00", "促销活动")
new("TJ002", "in", "TJ007", "小王", 18, "11:00", "17:00")

for c, t in list(tok.items()) + [("HR", hr)]:
    call("/api/logout", {}, t)
srv.shutdown()
print("演示资料已建立：%s（门店 6 家、伙伴 8 人、支援记录 11 笔，日期在 %d 年 %d 月）" % (server.DB_PATH, today.year, today.month))
print("高德金钥：%s" % ("已从正式版套用（%s）" % "、".join(k for k in copied if k != "dist_mode") if [k for k in copied if k != "dist_mode"] else "正式版尚未设定，演示版用直线距离、无地图"))
