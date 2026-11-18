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
import shutil
shutil.rmtree(os.path.join(os.path.dirname(server.DB_PATH), "photos"), ignore_errors=True)
os.makedirs(os.path.dirname(server.DB_PATH), exist_ok=True)
db.migrate(server.DB_PATH, do_backup=False)

# 从正式版复制高德金钥（只读开启正式版资料库，不会改动它）
KEYS = ("amap_key", "amap_sec", "amap_ws_key", "dist_mode", "ai_key", "ai_model")   # OSS 不复制：演示照片只存演示伺服器本地
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

# ---------------- 资产管理示范资料（v1.3）
import base64
call("/api/hr/accounts", {"code": "ZC", "name": "资产管理员", "role": "asset", "isNew": True}, hr)
call("/api/hr/accounts", {"code": "CW", "name": "财务", "role": "finance", "isNew": True}, hr)
zc = call("/api/login", {"code": "ZC"})["token"]
cw = call("/api/login", {"code": "CW"})["token"]
for n, cd, p in [("制冰机", "ZB", 12800), ("冷藏柜", "LC", 6500), ("萃茶机", "CC", 8800), ("封口机", "FK", 2300),
                 ("果糖机", "GT", 1800), ("开水机", "KS", 3200), ("收银机", "SY", 4500), ("展示冰柜", "ZG", 5600)]:
    call("/api/asset/items", {"name": n, "code": cd, "price": p}, zc)
y = today.year
ROWS, k = [], 0
for st, plan in [("TJ001", "ZB LC LC CC FK FK GT KS SY ZG"), ("TJ002", "ZB LC CC FK GT KS SY"), ("TJ005", "ZB ZB LC CC FK FK GT KS SY ZG"),
                 ("TJ007", "ZB LC CC FK GT KS SY"), ("TJ009", "ZB LC CC FK GT SY")]:
    for cd in plan.split():
        k += 1
        yr = y - 1 - (k % 3)
        name = {"ZB": "制冰机", "LC": "冷藏柜", "CC": "萃茶机", "FK": "封口机", "GT": "果糖机", "KS": "开水机", "SY": "收银机", "ZG": "展示冰柜"}[cd]
        ROWS.append("TJ-%s-%d-%04d\t%s\t%s\t%d-%02d\t\t%s\t" % (cd, yr, k, name, st, yr, (k % 12) + 1, "闲置" if k == 17 else "在用"))
call("/api/asset/import", {"text": "资产编号\t资产名称\t归属门店\t购入时间\t价格\t状态\t备注\n" + "\n".join(ROWS), "apply": True}, zc)
call("/api/asset/labels", {"mark": True}, zc)
with open(os.path.join(HERE, "demo_photo.jpg"), "rb") as f:
    PHOTO = f.read()
_n = [0]
def photo(t, ctx, no=""):
    _n[0] += 1   # JPEG 结尾附加不同位元组，避免被判为重复照片
    data = "data:image/jpeg;base64," + base64.b64encode(PHOTO + b"demo%d" % _n[0]).decode()
    return call("/api/asset/photo", {"data": data, "ctx": ctx, "assetNo": no}, t)["key"]
A = {}
for t in (tok["TJ001"], tok["TJ002"], tok["TJ005"], tok["TJ007"], tok["TJ009"]):
    for a in call("/api/asset/assets", tok=t)["assets"]:
        A.setdefault(a["store"], []).append(a)
# 调拨：奥城店制冰机 → 和平大悦城店（已审批，等奥城店出库）
zb = [a for a in A["TJ005"] if a["name"] == "制冰机"][1]
call("/api/asset/request", {"kind": "transfer", "dir": "in", "store": "TJ005", "ids": [zb["id"]], "reason": "旺季产能不足"}, tok["TJ001"])
mv = call("/api/asset/moves?status=pending", tok=zc)["moves"][0]
call("/api/asset/move/%d/decide" % mv["id"], {"ok": True}, zc)
# 调拨：天河城店闲置开水机 → 于家堡店（待审批）
ks = [a for a in A["TJ007"] if a["name"] == "开水机"][0]
call("/api/asset/request", {"kind": "transfer", "dir": "out", "store": "TJ009", "ids": [ks["id"]], "reason": "本店闲置，于家堡店缺开水机"}, tok["TJ007"])
# 报废：南开大悦城店封口机（待审批）
fk = [a for a in A["TJ002"] if a["name"] == "封口机"][0]
call("/api/asset/request", {"kind": "scrap", "ids": [fk["id"]], "reason": "损坏无法维修", "note": "加热片烧坏，维修报价超过半价",
                            "photos": [photo(tok["TJ002"], "scrap", fk["asset_no"])]}, tok["TJ002"])
# 已完成调拨：南开大悦城店果糖机 → 奥城店
gt = [a for a in A["TJ002"] if a["name"] == "果糖机"][0]
call("/api/asset/request", {"kind": "transfer", "dir": "out", "store": "TJ005", "ids": [gt["id"]], "reason": "门店装修暂停营业"}, tok["TJ002"])
mv = call("/api/asset/moves?status=pending", tok=zc)["moves"][0]
call("/api/asset/move/%d/decide" % mv["id"], {"ok": True}, zc)
call("/api/asset/move/%d/ship" % mv["id"], {"photos": [photo(tok["TJ002"], "ship", gt["asset_no"])]}, tok["TJ002"])
call("/api/asset/move/%d/receive" % mv["id"], {"photos": [photo(tok["TJ005"], "recv", gt["asset_no"])], "cond": "完好"}, tok["TJ005"])
# 财务购入：封口机 × 3（和平 1、于家堡 2；于家堡已入库 1 件）
items = {i["name"]: i["id"] for i in call("/api/asset/meta", tok=cw)["items"]}
exp = (today + datetime.timedelta(days=2)).isoformat()
call("/api/asset/purchase", {"item_id": items["封口机"], "buy_date": today.isoformat(), "expect_date": exp, "note": "门店扩产",
                             "alloc": [{"store": "TJ001", "qty": 1}, {"store": "TJ009", "qty": 2}]}, cw)
call("/api/asset/purchase", {"item_id": items["展示冰柜"], "price": 5900, "buy_date": (today - datetime.timedelta(days=12)).isoformat(),
                             "expect_date": (today - datetime.timedelta(days=8)).isoformat(), "alloc": [{"store": "TJ007", "qty": 1}]}, cw)
si = [m for m in call("/api/asset/store/home", tok=tok["TJ009"])["todo"] if m["kind"] == "stockin"][0]
call("/api/asset/move/%d/receive" % si["id"], {"photos": [photo(tok["TJ009"], "stockin", si["asset_no"])], "cond": "完好"}, tok["TJ009"])
# 盘点：和平大悦城店、南开大悦城店，和平已盘一部分
end = (today + datetime.timedelta(days=5)).isoformat()
tk = call("/api/asset/count", {"name": "%d 年 %d 月资产盘点" % (today.year, today.month), "ctype": "月度盘点", "stores": ["TJ001", "TJ002"], "items": "all",
                               "start_date": today.isoformat(), "end_date": end, "review_date": end, "note": "后场与仓库设备也要盘"}, zc)
lines = call("/api/asset/count/detail?id=%d" % tk["id"], tok=tok["TJ001"])["lines"]
for i, l in enumerate(lines[:6]):
    if i == 4:
        call("/api/asset/count/line", {"id": l["id"], "missing": True, "note": "店内找不到，可能之前借给别店"}, tok["TJ001"])
    else:
        call("/api/asset/count/line", {"id": l["id"], "photos": [photo(tok["TJ001"], "count", l["asset_no"])], "cond": "损坏待修" if i == 2 else "正常",
                                       "note": "门把松动" if i == 2 else ""}, tok["TJ001"])
call("/api/asset/count/extra", {"task": tk["id"], "name": "果糖机", "photos": [photo(tok["TJ001"], "count")], "note": "仓库发现，无标签"}, tok["TJ001"])
for t in (zc, cw):
    call("/api/logout", {}, t)

for c, t in list(tok.items()) + [("HR", hr)]:
    call("/api/logout", {}, t)
srv.shutdown()
print("演示资料已建立：%s（门店 6 家、伙伴 8 人、支援记录 11 笔、资产 40 件，日期在 %d 年 %d 月）" % (server.DB_PATH, today.year, today.month))
print("高德金钥：%s" % ("已从正式版套用（%s）" % "、".join(k for k in copied if k != "dist_mode") if [k for k in copied if k != "dist_mode"] else "正式版尚未设定，演示版用直线距离、无地图"))
