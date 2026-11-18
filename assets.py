"""
资产管理模块（v1.3）：资产目录、资产、履历、照片（压缩上传、OSS、AI 检测）、调拨 / 报废 / 财务购入→门店入库、标签、导入导出。
由 server.py 在启动时呼叫 init(globals()) 挂上路由。
角色：store 门店、asset 资产管理员、finance 财务。
"""
import os
import re
import io
import hmac
import json
import time
import uuid
import base64
import hashlib
import datetime
import threading
import urllib.parse
import urllib.request
from email.utils import formatdate

import qr

G = {}            # server.py 的全域（route、ApiError、one、rows…）
STATUS = {"pending_in": "待入库", "active": "在用", "transit": "调拨中", "scrapped": "已报废", "lost": "盘亏"}
CONDS = ["正常", "闲置", "损坏待修"]
MOVE_KIND = {"transfer": "调拨", "scrap": "报废", "stockin": "购入入库"}
MOVE_STATUS = {"pending": "待审批", "approved": "待出库", "shipped": "待收货", "done": "已完成",
               "rejected": "已驳回", "cancelled": "已撤回", "refused": "已拒收"}
EVENT = {"import": "初始导入", "create": "新增资产", "edit": "修改资料", "purchase": "财务购入", "stockin": "门店入库",
         "stockin_refused": "入库拒收", "transfer_req": "申请调拨", "transfer_ok": "调拨审批同意", "transfer_rej": "调拨驳回",
         "transfer_direct": "资产管理员直接调拨", "ship": "调出店出库", "receive": "调入店收货", "transfer_refused": "调入店拒收",
         "transfer_cancel": "撤回调拨", "scrap_req": "申请报废", "scrapped": "已报废", "scrap_rej": "报废驳回",
         "scrap_cancel": "撤回报废", "count": "盘点", "lost": "盘亏", "found": "盘盈登记", "review": "盘点复核"}


# ------------------------------------------------------------------ 工具
def _g(name):
    return G[name]


def ApiError(msg, status=400):
    return G["ApiError"](msg, status)


def now_ms():
    return G["now_ms"]()


def one(c, sql, args=()):
    return G["one"](c, sql, args)


def rows(c, sql, args=()):
    return G["rows"](c, sql, args)


def settings(c):
    from db import ASSET_SETTING_DEFAULTS
    cfg = dict(ASSET_SETTING_DEFAULTS)
    for r in c.execute("SELECT key, value FROM settings"):
        cfg[r["key"]] = r["value"]
    return cfg


def store_map(c):
    return {r["code"]: r["name"] for r in rows(c, "SELECT code, name FROM accounts WHERE role='store'")}


def add_event(c, asset_id, who, kind, detail="", photos=None):
    c.execute("INSERT INTO asset_events(asset_id, t, who, kind, detail, photos) VALUES(?,?,?,?,?,?)",
              (asset_id, now_ms(), who, kind, detail or "", json.dumps(photos or [])))


def jl(s):
    try:
        return json.loads(s) if s else []
    except ValueError:
        return []


def norm_no(s):
    return re.sub(r"[\s_—–]", "-", (s or "").strip().upper())


def parse_date(v):
    """接受 2025-06、2025-06-12、2025/6/12、2025.6、Excel 日期序号。回传 YYYY-MM-DD 或 YYYY-MM。"""
    s = str(v or "").strip()
    if not s:
        return None
    if re.match(r"^\d{5}(\.0+)?$", s):     # Excel 日期序号
        d = datetime.date(1899, 12, 30) + datetime.timedelta(days=int(float(s)))
        return d.isoformat()
    m = re.match(r"^(\d{4})[-/.年](\d{1,2})(?:[-/.月](\d{1,2})日?)?(?:\s.*)?$", s)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), m.group(3)
    if not (1990 <= y <= 2100 and 1 <= mo <= 12):
        return None
    if d:
        try:
            return datetime.date(y, mo, int(d)).isoformat()
        except ValueError:
            return None
    return "%04d-%02d" % (y, mo)


def next_numbers(c, code, year, n):
    """示例编号规则：前缀-品项代码-年份-4 位流水号。"""
    prefix = settings(c).get("asset_no_prefix") or "TJ"
    code = (code or "ZC").upper()
    head = "%s-%s-%s-" % (prefix, code, year)
    mx = 0
    for r in rows(c, "SELECT asset_no FROM assets WHERE asset_no LIKE ?", (head + "%",)):
        m = re.match(r"^.*-(\d+)$", r["asset_no"])
        if m:
            mx = max(mx, int(m.group(1)))
    return [head + "%04d" % (mx + i + 1) for i in range(n)]


def locked_assets(c):
    """进行中的盘点任务所含资产：调拨 / 报废审批暂停。"""
    out = set()
    for t in rows(c, "SELECT id, rules FROM count_tasks WHERE status='open'"):
        try:
            if not json.loads(t["rules"] or "{}").get("lock", True):
                continue
        except ValueError:
            pass
        out |= {r["asset_id"] for r in rows(c, "SELECT asset_id FROM count_lines WHERE task_id=? AND asset_id IS NOT NULL", (t["id"],))}
    return out


def asset_view(c, a, smap=None):
    smap = smap or store_map(c)
    d = dict(a)
    d["store_name"] = smap.get(a["store"], a["store"] or "")
    d["status_text"] = STATUS.get(a["status"], a["status"])
    return d


# ------------------------------------------------------------------ 照片：签名网址、OSS、AI
PHOTO_DIR = None


def photo_url(c, key, thumb=False, secret=None):
    if not key:
        return ""
    secret = secret or settings(c)["photo_secret"]
    exp = int(time.time()) + 6 * 3600
    t = "1" if thumb else "0"
    sig = hmac.new(secret.encode(), ("%s|%d|%s" % (key, exp, t)).encode(), hashlib.sha256).hexdigest()[:24]
    return "/p/%s?e=%d&t=%s&s=%s" % (urllib.parse.quote(key), exp, t, sig)


def photos_out(c, keys):
    sec = settings(c)["photo_secret"]
    return [{"key": k, "url": photo_url(c, k, False, sec), "thumb": photo_url(c, k, True, sec)} for k in (keys or [])]


def oss_ready(cfg):
    return bool(cfg.get("oss_bucket") and cfg.get("oss_ak_id") and cfg.get("oss_ak_secret"))


def _oss_host(cfg):
    return "%s.%s.aliyuncs.com" % (cfg["oss_bucket"], cfg.get("oss_region") or "oss-cn-beijing")


def oss_put(cfg, key, data, ctype="image/jpeg"):
    date = formatdate(usegmt=True)
    sts = "PUT\n\n%s\n%s\n/%s/%s" % (ctype, date, cfg["oss_bucket"], key)
    sig = base64.b64encode(hmac.new(cfg["oss_ak_secret"].encode(), sts.encode(), hashlib.sha1).digest()).decode()
    req = urllib.request.Request("https://%s/%s" % (_oss_host(cfg), urllib.parse.quote(key)), data=data, method="PUT",
                                 headers={"Date": date, "Content-Type": ctype, "Authorization": "OSS %s:%s" % (cfg["oss_ak_id"], sig)})
    with urllib.request.urlopen(req, timeout=20) as r:
        if r.status not in (200, 201):
            raise IOError("OSS %s" % r.status)


def oss_signed_get(cfg, key, thumb=False, ttl=3600):
    exp = int(time.time()) + ttl
    proc = "image/resize,w_400" if thumb else ""
    res = "/%s/%s" % (cfg["oss_bucket"], key) + ("?x-oss-process=" + proc if proc else "")
    sts = "GET\n\n\n%d\n%s" % (exp, res)
    sig = base64.b64encode(hmac.new(cfg["oss_ak_secret"].encode(), sts.encode(), hashlib.sha1).digest()).decode()
    q = {"OSSAccessKeyId": cfg["oss_ak_id"], "Expires": str(exp), "Signature": sig}
    if proc:
        q["x-oss-process"] = proc
    return "https://%s/%s?%s" % (_oss_host(cfg), urllib.parse.quote(key), urllib.parse.urlencode(q))


def ai_check(cfg, img, item_name, asset_no):
    """阿里云百炼通义千问 VL。回传 dict（verdict: ok / doubt / fail / skip）。"""
    if not cfg.get("ai_key"):
        return {"verdict": "skip", "reason": "尚未设定 AI 金钥，略过检测"}
    prompt = ("这是一张门店资产照片。预期品项：「%s」%s。请判断：1) 照片中的主要设备是不是这个品项；"
              "2) 是否看得到资产标签，标签上的编号是什么；3) 是否像是翻拍屏幕或翻拍照片。"
              "只回传 JSON，不要其他文字：{\"is_item\":true或false,\"label_visible\":true或false,"
              "\"label_text\":\"标签上的编号\",\"recapture\":true或false,\"reason\":\"一句中文说明\"}"
              ) % (item_name or "（未指定）", "，预期资产编号：「%s」" % asset_no if asset_no else "")
    body = {"model": cfg.get("ai_model") or "qwen-vl-plus",
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(img).decode()}},
                {"type": "text", "text": prompt}]}]}
    try:
        req = urllib.request.Request("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                                     data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": "Bearer " + cfg["ai_key"], "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            out = json.loads(r.read().decode("utf-8"))
        txt = out["choices"][0]["message"]["content"]
        if isinstance(txt, list):
            txt = "".join(p.get("text", "") for p in txt if isinstance(p, dict))
        m = re.search(r"\{.*\}", txt, re.S)
        res = json.loads(m.group(0)) if m else {}
    except Exception as e:
        return {"verdict": "skip", "reason": "AI 检测暂时无法使用（%s），已略过" % str(e)[:60]}
    is_item = bool(res.get("is_item"))
    seen = bool(res.get("label_visible"))
    label = norm_no(res.get("label_text") or "")
    match = bool(asset_no) and seen and norm_no(asset_no) == label
    if not is_item or res.get("recapture"):
        verdict = "fail"
    elif asset_no and not match:
        verdict = "doubt"
    else:
        verdict = "ok"
    return {"verdict": verdict, "is_item": is_item, "label_visible": seen, "label_text": res.get("label_text") or "",
            "label_match": match, "recapture": bool(res.get("recapture")), "reason": (res.get("reason") or "")[:120]}


def upload_pending_once(db_path):
    """OSS 暂时失败的照片：补传，成功后删除本地档。"""
    import db
    c = db.connect(db_path)
    try:
        cfg = settings(c)
        if not oss_ready(cfg):
            return
        for p in rows(c, "SELECT * FROM asset_photos WHERE location='pending' ORDER BY id LIMIT 50"):
            fp = os.path.join(PHOTO_DIR, p["key"])
            if not os.path.exists(fp):
                continue
            try:
                with open(fp, "rb") as f:
                    oss_put(cfg, p["key"], f.read())
            except Exception:
                return
            c.execute("UPDATE asset_photos SET location='oss' WHERE id=?", (p["id"],))
            c.commit()
            os.remove(fp)
    finally:
        c.close()


def serve_photo(h, u):
    """GET /p/<key>?e=&t=&s=：验证签名后，OSS 照片转到限时网址，本地照片直接回传。"""
    import db
    key = urllib.parse.unquote(u.path[3:])
    q = dict(urllib.parse.parse_qsl(u.query))
    if ".." in key or key.startswith("/") or not re.match(r"^[A-Za-z0-9_./-]+$", key):
        return h.send(404, {"error": "not found"})
    c = db.connect(G["DB_PATH"])
    try:
        cfg = settings(c)
        try:
            exp = int(q.get("e", "0"))
        except ValueError:
            exp = 0
        want = hmac.new(cfg["photo_secret"].encode(), ("%s|%d|%s" % (key, exp, q.get("t", "0"))).encode(), hashlib.sha256).hexdigest()[:24]
        if exp < time.time() or not hmac.compare_digest(want, q.get("s", "")):
            return h.send(403, {"error": "链接已过期，请重新整理页面"})
        p = one(c, "SELECT * FROM asset_photos WHERE key=?", (key,))
        if not p:
            return h.send(404, {"error": "not found"})
        if p["location"] == "oss" and oss_ready(cfg):
            return h.send(302, b"", "text/plain", {"Location": oss_signed_get(cfg, key, q.get("t") == "1")})
        fp = os.path.join(PHOTO_DIR, key)
        if not os.path.exists(fp):
            return h.send(404, {"error": "not found"})
        with open(fp, "rb") as f:
            data = f.read()
        return h.send(200, data, "image/jpeg", {"Cache-Control": "private, max-age=3600"})
    finally:
        c.close()


def start_worker():
    def loop():
        while True:
            time.sleep(60)
            try:
                upload_pending_once(G["DB_PATH"])
            except Exception:
                pass
            time.sleep(540)
    threading.Thread(target=loop, daemon=True).start()


# ------------------------------------------------------------------ 路由
def init(g):
    global PHOTO_DIR, G
    G = g
    route, Tx, write_log = g["route"], g["Tx"], g["write_log"]
    xlsx = g["xlsx"]
    PHOTO_DIR = os.path.join(os.path.dirname(g["DB_PATH"]), "photos")
    os.makedirs(PHOTO_DIR, exist_ok=True)


    def need(req, *roles):
        if req.me["role"] not in roles:
            raise ApiError("无权使用此功能", 403)

    def item_or_404(c, iid):
        it = one(c, "SELECT * FROM asset_items WHERE id=?", (iid,))
        if not it:
            raise ApiError("品项不存在")
        return it

    # ---------------- 共用资料
    @route("GET", "/api/asset/meta")
    def api_meta(req):
        need(req, "store", "asset", "finance")
        c = req.conn
        cfg = settings(c)
        return {"items": rows(c, "SELECT id, name, code, price, active FROM asset_items ORDER BY active DESC, name"),
                "stores": rows(c, "SELECT code, name FROM accounts WHERE role='store' AND active=1 ORDER BY code"),
                "conds": CONDS, "status": STATUS, "moveKind": MOVE_KIND, "moveStatus": MOVE_STATUS, "events": EVENT,
                "prefix": cfg.get("asset_no_prefix"), "aiOn": bool(cfg.get("ai_key")), "ossOn": oss_ready(cfg)}

    # ---------------- 照片
    @route("POST", "/api/asset/photo")
    def api_photo(req):
        need(req, "store", "asset", "finance")
        c, b = req.conn, req.body
        raw = b.get("data") or ""
        if "," in raw[:80]:
            raw = raw.split(",", 1)[1]
        try:
            img = base64.b64decode(raw)
        except Exception:
            raise ApiError("照片格式不正确")
        if len(img) < 2000 or img[:2] != b"\xff\xd8":
            raise ApiError("照片格式不正确，请重新拍摄")
        if len(img) > 3 * 1024 * 1024:
            raise ApiError("照片太大")
        ctx = re.sub(r"[^a-z]", "", (b.get("ctx") or "photo"))[:12] or "photo"
        asset_no = norm_no(b.get("assetNo") or "")
        store = req.me["code"] if req.me["role"] == "store" else re.sub(r"[^A-Za-z0-9_-]", "", b.get("store") or "")[:30]
        sha = hashlib.sha256(img).hexdigest()
        dup = one(c, "SELECT key, created_at FROM asset_photos WHERE sha=?", (sha,))
        cfg = settings(c)
        ai = ai_check(cfg, img, b.get("itemName") or "", asset_no) if b.get("check") else {"verdict": "skip", "reason": ""}
        if dup:
            ai.update({"verdict": "fail", "dup": True, "reason": "这张照片之前已上传过（%s），请现场重新拍摄" % G["fmt_ts"](dup["created_at"])})
        key = "asset/%s/%s/%s_%s_%s.jpg" % (datetime.date.today().strftime("%Y-%m"), store or "x",
                                           re.sub(r"[^A-Za-z0-9-]", "", asset_no or ctx)[:40] or ctx,
                                           datetime.datetime.now().strftime("%Y%m%dT%H%M%S"), uuid.uuid4().hex[:6])
        fp = os.path.join(PHOTO_DIR, key)
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        location = "local"
        if oss_ready(cfg):
            try:
                oss_put(cfg, key, img)
                location = "oss"
            except Exception:
                location = "pending"
        if location != "oss":
            with open(fp, "wb") as f:
                f.write(img)
        c.execute("""INSERT INTO asset_photos(key, store, asset_no, ctx, sha, size, location, ai, created_by, created_at)
                     VALUES(?,?,?,?,?,?,?,?,?,?)""", (key, store, asset_no, ctx, sha, len(img), location, json.dumps(ai, ensure_ascii=False),
                                                      req.me["code"], now_ms()))
        c.commit()
        return {"key": key, "url": photo_url(c, key), "thumb": photo_url(c, key, True), "ai": ai, "size": len(img)}

    def check_photos(c, keys, need_n=1):
        keys = [k for k in (keys or []) if isinstance(k, str)]
        if len(keys) < need_n:
            raise ApiError("请上传照片")
        for k in keys:
            if not one(c, "SELECT 1 AS x FROM asset_photos WHERE key=?", (k,)):
                raise ApiError("照片不存在，请重新上传")
        return keys

    def photo_ai(c, keys):
        """取这几张照片里最好的 AI 结果。"""
        best = None
        order = {"ok": 3, "skip": 2, "doubt": 1, "fail": 0}
        for k in keys or []:
            p = one(c, "SELECT ai FROM asset_photos WHERE key=?", (k,))
            a = json.loads(p["ai"]) if p and p["ai"] else {"verdict": "skip"}
            if best is None or order.get(a.get("verdict"), 2) > order.get(best.get("verdict"), 2):
                best = a
        return best or {"verdict": "skip"}

    # ---------------- 资产目录
    @route("POST", "/api/asset/items")
    def api_item_save(req):
        need(req, "asset")
        c, b = req.conn, req.body
        name = (b.get("name") or "").strip()[:40]
        code = re.sub(r"[^A-Za-z0-9]", "", b.get("code") or "").upper()[:6]
        try:
            price = round(float(b.get("price") or 0), 2)
        except ValueError:
            raise ApiError("价格请填数字")
        if not name:
            raise ApiError("请填品项名称")
        if not code:
            raise ApiError("请填品项代码（英文字母，用于资产编号，例如制冰机 ZB）")
        if price < 0:
            raise ApiError("价格不正确")
        with Tx(c):
            if b.get("id"):
                old = item_or_404(c, b["id"])
                if one(c, "SELECT 1 AS x FROM asset_items WHERE name=? AND id<>?", (name, old["id"])):
                    raise ApiError("品项名称重复")
                c.execute("UPDATE asset_items SET name=?, code=?, price=?, active=? WHERE id=?",
                          (name, code, price, 1 if b.get("active", True) else 0, old["id"]))
                c.execute("UPDATE assets SET name=? WHERE item_id=?", (name, old["id"]))
            else:
                if one(c, "SELECT 1 AS x FROM asset_items WHERE name=?", (name,)):
                    raise ApiError("品项名称重复")
                c.execute("INSERT INTO asset_items(name, code, price, active, created_at) VALUES(?,?,?,1,?)", (name, code, price, now_ms()))
            write_log(c, req, "资产目录", "%s（%s）¥%g" % (name, code, price))
        return {"ok": True}

    # ---------------- 资产清单 / 履历
    @route("GET", "/api/asset/assets")
    def api_assets(req):
        c, q = req.conn, req.q
        role = req.me["role"]
        need(req, "store", "asset", "finance")
        where, args = ["1=1"], []
        if role == "store":
            st = q.get("store") or req.me["code"]
            if st != req.me["code"]:      # 门店查看别店资产（调入申请用）：只给在用资产的基本资料
                where.append("status='active'")
            where.append("store=?")
            args.append(st)
        elif q.get("store"):
            where.append("store=?")
            args.append(q["store"])
        if q.get("item"):
            where.append("item_id=?")
            args.append(int(q["item"]))
        st = q.get("status") or ("live" if role == "store" else "")
        if st == "live":
            where.append("status IN ('active','transit','pending_in')")
        elif st:
            where.append("status=?")
            args.append(st)
        if q.get("q"):
            where.append("(asset_no LIKE ? OR name LIKE ? OR note LIKE ?)")
            args += ["%" + q["q"] + "%"] * 3
        if q.get("unprinted"):
            where.append("label_printed=0")
        smap = store_map(c)
        lst = [asset_view(c, a, smap) for a in rows(c, "SELECT * FROM assets WHERE %s ORDER BY store, name, asset_no LIMIT 3000" % " AND ".join(where), args)]
        locked = locked_assets(c)
        busy = {r["asset_id"] for r in rows(c, "SELECT asset_id FROM asset_moves WHERE status IN ('pending','approved','shipped')")}
        for a in lst:
            a["locked"] = a["id"] in locked
            a["busy"] = a["id"] in busy
        return {"assets": lst, "total": len(lst), "value": round(sum(a["price"] or 0 for a in lst if a["status"] in ("active", "transit")), 2)}

    @route("GET", "/api/asset/detail")
    def api_detail(req):
        need(req, "store", "asset", "finance")
        c = req.conn
        a = one(c, "SELECT * FROM assets WHERE id=?", (int(req.q.get("id") or 0),))
        if not a or (req.me["role"] == "store" and a["store"] != req.me["code"]):
            raise ApiError("资产不存在", 404)
        smap = store_map(c)
        ev = rows(c, "SELECT * FROM asset_events WHERE asset_id=? ORDER BY id DESC", (a["id"],))
        for e in ev:
            e["photos"] = photos_out(c, jl(e["photos"]))
            e["kind_text"] = EVENT.get(e["kind"], e["kind"])
            e["who_name"] = G["acc_name"](c, e["who"])
        return {"asset": asset_view(c, a, smap), "events": ev}

    @route("POST", "/api/asset/asset")
    def api_asset_save(req):
        need(req, "asset")
        c, b = req.conn, req.body
        no = norm_no(b.get("asset_no"))
        it = item_or_404(c, b.get("item_id"))
        store = b.get("store") or ""
        if not one(c, "SELECT 1 AS x FROM accounts WHERE code=? AND role='store'", (store,)):
            raise ApiError("请选择门店")
        bd = parse_date(b.get("buy_date")) or ""
        cond = b.get("cond") if b.get("cond") in CONDS else "正常"
        try:
            price = round(float(b.get("price") if b.get("price") not in (None, "") else it["price"]), 2)
        except ValueError:
            raise ApiError("价格请填数字")
        with Tx(c):
            if b.get("id"):
                a = one(c, "SELECT * FROM assets WHERE id=?", (b["id"],))
                if not a:
                    raise ApiError("资产不存在")
                if no and no != a["asset_no"] and one(c, "SELECT 1 AS x FROM assets WHERE asset_no=?", (no,)):
                    raise ApiError("资产编号已存在")
                ch = []
                for k, v, lab in (("asset_no", no or a["asset_no"], "编号"), ("item_id", it["id"], "品项"), ("store", store, "门店"),
                                  ("buy_date", bd, "购入时间"), ("price", price, "价格"), ("cond", cond, "状况"), ("note", (b.get("note") or "")[:100], "备注")):
                    if a[k] != v:
                        ch.append("%s：%s → %s" % (lab, a[k], v))
                if store != a["store"] and a["status"] != "active":
                    raise ApiError("这件资产调拨中或尚未入库，不能直接改门店")
                c.execute("""UPDATE assets SET asset_no=?, item_id=?, name=?, store=?, buy_date=?, price=?, cond=?, note=?, updated_at=? WHERE id=?""",
                          (no or a["asset_no"], it["id"], it["name"], store, bd, price, cond, (b.get("note") or "")[:100], now_ms(), a["id"]))
                if ch:
                    add_event(c, a["id"], req.me["code"], "edit", "；".join(ch))
                aid = a["id"]
            else:
                if not no:
                    no = next_numbers(c, it["code"], (bd or datetime.date.today().isoformat())[:4], 1)[0]
                if one(c, "SELECT 1 AS x FROM assets WHERE asset_no=?", (no,)):
                    raise ApiError("资产编号已存在")
                cur = c.execute("""INSERT INTO assets(asset_no, item_id, name, store, buy_date, price, status, cond, note, created_at, updated_at)
                                   VALUES(?,?,?,?,?,?,'active',?,?,?,?)""", (no, it["id"], it["name"], store, bd, price, cond, (b.get("note") or "")[:100], now_ms(), now_ms()))
                aid = cur.lastrowid
                add_event(c, aid, req.me["code"], "create", "%s · %s" % (no, G["acc_name"](c, store)))
            write_log(c, req, "资产维护", no)
        return {"ok": True, "id": aid}

    # ---------------- 导入 / 导出
    IMPORT_COLS = {"资产编号": "no", "编号": "no", "资产名称": "name", "名称": "name", "品项": "name", "归属门店": "store",
                   "门店": "store", "门店编号": "store", "购入时间": "date", "购入日期": "date", "价格": "price", "单价": "price",
                   "状态": "cond", "状况": "cond", "备注": "note"}

    @route("GET", "/api/asset/template")
    def api_tpl(req):
        need(req, "asset")
        data = xlsx.write([("资产导入", [["资产编号*", "资产名称*", "归属门店*", "购入时间*", "价格", "状态", "备注"],
                                     ["TJ-ZB-2025-0001", "制冰机", "TJ005", "2025-03", "", "在用", ""]], [18, 14, 12, 12, 10, 10, 20])])
        return {"__file__": data, "filename": "资产导入模板.xlsx", "type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}

    def parse_import(c, b):
        grid = []
        if b.get("file"):
            raw = base64.b64decode(b["file"].split(",", 1)[-1])
            if raw[:2] == b"PK":
                grid = xlsx.read_xlsx(raw)
            else:
                for enc in ("utf-8-sig", "gb18030"):
                    try:
                        txt = raw.decode(enc)
                        break
                    except UnicodeDecodeError:
                        txt = None
                grid = [re.split(r"[,\t]", ln) for ln in (txt or "").splitlines()]
        elif b.get("text"):
            grid = [ln.split("\t") if "\t" in ln else re.split(r"\s{2,}|,", ln) for ln in b["text"].splitlines()]
        grid = [[str(x).strip() for x in r] for r in grid if any(str(x).strip() for x in r)]
        if not grid:
            raise ApiError("档案是空的")
        head = [IMPORT_COLS.get(h.replace("*", "").strip()) for h in grid[0]]
        if "no" in head and "name" in head:
            body = grid[1:]
        else:
            head = ["no", "name", "store", "date", "price", "cond", "note"]
            body = grid
        items = {r["name"]: r for r in rows(c, "SELECT * FROM asset_items")}
        stores = rows(c, "SELECT code, name FROM accounts WHERE role='store'")
        by_code = {s["code"].upper(): s["code"] for s in stores}
        by_name = {s["name"]: s["code"] for s in stores}
        exist = {r["asset_no"]: r for r in rows(c, "SELECT * FROM assets")}
        seen, plan, new_items = {}, [], {}
        for i, r in enumerate(body):
            d = {k: (r[j] if j < len(r) else "") for j, k in enumerate(head) if k}
            line = i + (2 if head is not None and "no" in head and body is not grid else 1)
            p = {"line": line, "no": norm_no(d.get("no")), "name": (d.get("name") or "").strip(), "raw_store": d.get("store", "")}
            errs = []
            if not p["no"]:
                errs.append("缺资产编号")
            elif p["no"] in seen:
                errs.append("编号与第 %d 行重复" % seen[p["no"]])
            else:
                seen[p["no"]] = line
            if not p["name"]:
                errs.append("缺资产名称")
            st = by_code.get((d.get("store") or "").strip().upper()) or by_name.get((d.get("store") or "").strip())
            if not st:
                errs.append("门店「%s」不存在" % (d.get("store") or ""))
            p["store"] = st
            dt = parse_date(d.get("date"))
            if not dt:
                errs.append("购入时间「%s」看不懂" % (d.get("date") or ""))
            p["date"] = dt
            pr = (d.get("price") or "").replace(",", "").replace("¥", "").replace("元", "")
            try:
                p["price"] = round(float(pr), 2) if pr else None
            except ValueError:
                errs.append("价格「%s」不是数字" % pr)
                p["price"] = None
            cond = (d.get("cond") or "").strip()
            p["cond"] = "正常" if cond in ("", "在用", "正常") else cond if cond in CONDS else "正常"
            p["note"] = (d.get("note") or "")[:100]
            if p["name"] and p["name"] not in items:
                new_items.setdefault(p["name"], p["price"])
                p["new_item"] = True
            if errs:
                p["st"], p["msg"] = "error", "；".join(errs)
            elif p["no"] in exist:
                p["st"] = "update"
            else:
                p["st"] = "new"
            plan.append(p)
        return plan, new_items

    @route("POST", "/api/asset/import")
    def api_import(req):
        need(req, "asset")
        c, b = req.conn, req.body
        plan, new_items = parse_import(c, b)
        opts = b.get("opts") or {}
        add_items = opts.get("addItems", True)
        upd = opts.get("update", True)
        if not add_items:
            for p in plan:
                if p.get("new_item") and p["st"] != "error":
                    p["st"], p["msg"] = "error", "「%s」不在资产目录" % p["name"]
        summary = {"new": sum(1 for p in plan if p["st"] == "new"), "update": sum(1 for p in plan if p["st"] == "update"),
                   "error": sum(1 for p in plan if p["st"] == "error"), "newItems": len(new_items) if add_items else 0, "rows": len(plan)}
        if not b.get("apply"):
            return {"plan": plan[:500], "summary": summary, "newItems": list(new_items)}
        batch = "imp-%s-%s" % (datetime.datetime.now().strftime("%Y%m%d%H%M%S"), uuid.uuid4().hex[:4])
        per_store = {}
        with Tx(c):
            if add_items:
                for name, price in new_items.items():
                    code = "X%d" % (one(c, "SELECT COUNT(*) AS n FROM asset_items")["n"] + 1)
                    c.execute("INSERT OR IGNORE INTO asset_items(name, code, price, active, created_at) VALUES(?,?,?,1,?)",
                              (name, code, price or 0, now_ms()))
            items = {r["name"]: r for r in rows(c, "SELECT * FROM asset_items")}
            for p in plan:
                if p["st"] == "error" or (p["st"] == "update" and not upd):
                    continue
                it = items[p["name"]]
                price = p["price"] if p["price"] is not None else it["price"]
                if p["st"] == "new":
                    cur = c.execute("""INSERT INTO assets(asset_no, item_id, name, store, buy_date, price, status, cond, note, import_batch, created_at, updated_at)
                                       VALUES(?,?,?,?,?,?,'active',?,?,?,?,?)""",
                                    (p["no"], it["id"], it["name"], p["store"], p["date"], price, p["cond"], p["note"], batch, now_ms(), now_ms()))
                    add_event(c, cur.lastrowid, req.me["code"], "import", "%s · %s" % (p["no"], G["acc_name"](c, p["store"])))
                else:
                    a = one(c, "SELECT * FROM assets WHERE asset_no=?", (p["no"],))
                    c.execute("UPDATE assets SET item_id=?, name=?, buy_date=?, price=?, cond=?, note=?, updated_at=? WHERE id=?",
                              (it["id"], it["name"], p["date"], price, p["cond"], p["note"], now_ms(), a["id"]))
                    if a["store"] != p["store"] and a["status"] == "active":
                        c.execute("UPDATE assets SET store=? WHERE id=?", (p["store"], a["id"]))
                    add_event(c, a["id"], req.me["code"], "edit", "导入更新")
                ps = per_store.setdefault(p["store"], {"n": 0, "value": 0})
                ps["n"] += 1
                ps["value"] += price or 0
            write_log(c, req, "现存资产导入", "新增 %d、更新 %d、错误 %d（批次 %s）" % (summary["new"], summary["update"], summary["error"], batch))
        smap = store_map(c)
        return {"ok": True, "batch": batch, "summary": summary,
                "stores": sorted([{"store": k, "name": smap.get(k, k), "n": v["n"], "value": round(v["value"], 2)} for k, v in per_store.items()], key=lambda x: x["store"]),
                "errors": [p for p in plan if p["st"] == "error"]}

    @route("POST", "/api/asset/import/undo")
    def api_import_undo(req):
        need(req, "asset")
        c, batch = req.conn, (req.body.get("batch") or "")
        ids = [r["id"] for r in rows(c, "SELECT id FROM assets WHERE import_batch=?", (batch,))]
        if not ids:
            raise ApiError("找不到这批导入")
        ts = int(batch.split("-")[1][:14] and time.mktime(datetime.datetime.strptime(batch.split("-")[1], "%Y%m%d%H%M%S").timetuple()))
        if time.time() - ts > 86400:
            raise ApiError("超过 24 小时，不能整批撤销")
        ph = ",".join("?" * len(ids))
        if one(c, "SELECT 1 AS x FROM asset_moves WHERE asset_id IN (%s)" % ph, ids) or one(c, "SELECT 1 AS x FROM count_lines WHERE asset_id IN (%s)" % ph, ids):
            raise ApiError("这批资产已有调拨、报废或盘点记录，不能整批撤销")
        with Tx(c):
            c.execute("DELETE FROM asset_events WHERE asset_id IN (%s)" % ph, ids)
            c.execute("DELETE FROM assets WHERE id IN (%s)" % ph, ids)
            write_log(c, req, "撤销资产导入", "%s：%d 件" % (batch, len(ids)))
        return {"ok": True, "n": len(ids)}

    @route("GET", "/api/asset/export")
    def api_export(req):
        need(req, "asset", "finance")
        c, kind = req.conn, req.q.get("kind") or "assets"
        smap = store_map(c)
        sn = lambda s: smap.get(s, s or "")
        if kind == "assets":
            head = ["资产编号", "资产名称", "归属门店编号", "归属门店", "购入时间", "价格", "状态", "状况", "备注", "标签已打印"]
            data = [[a["asset_no"], a["name"], a["store"], sn(a["store"]), a["buy_date"], a["price"], STATUS.get(a["status"]), a["cond"], a["note"], "是" if a["label_printed"] else "否"]
                    for a in rows(c, "SELECT * FROM assets ORDER BY store, name, asset_no")]
            sheets, fname = [("资产清单", [head] + data, [18, 14, 10, 14, 12, 10, 8, 10, 20, 8])], "资产清单"
        elif kind == "moves":
            head = ["类型", "状态", "资产编号", "资产名称", "调出 / 原门店", "调入 / 入库门店", "原因", "说明", "申请人", "申请时间", "审批", "出库时间", "收货 / 入库时间", "到货状况", "收货说明"]
            data = []
            for m in rows(c, "SELECT m.*, a.asset_no, a.name FROM asset_moves m JOIN assets a ON a.id=m.asset_id ORDER BY m.id DESC"):
                data.append([MOVE_KIND.get(m["kind"]), MOVE_STATUS.get(m["status"]), m["asset_no"], m["name"], sn(m["from_store"]), sn(m["to_store"]),
                             m["reason"], m["note"], G["acc_name"](c, m["created_by"]), G["fmt_ts"](m["created_at"]),
                             (G["acc_name"](c, m["decided_by"]) + " " + G["fmt_ts"](m["decided_at"])).strip() if m["decided_by"] else "",
                             G["fmt_ts"](m["ship_at"]), G["fmt_ts"](m["recv_at"]), m["recv_cond"], m["recv_note"]])
            sheets, fname = [("调拨报废入库", [head] + data, [8, 8, 18, 12, 12, 12, 14, 20, 10, 16, 20, 16, 16, 10, 20])], "调拨报废入库记录"
        elif kind == "purchases":
            head = ["购入日期", "品项", "单价", "数量", "金额", "分配门店", "已入库", "预计到货", "备注", "发起人"]
            data = []
            for p in rows(c, "SELECT * FROM purchases ORDER BY id DESC"):
                mv = rows(c, "SELECT to_store, status FROM asset_moves WHERE purchase_id=?", (p["id"],))
                alloc = {}
                for m in mv:
                    alloc[sn(m["to_store"])] = alloc.get(sn(m["to_store"]), 0) + 1
                data.append([p["buy_date"], p["name"], p["price"], p["qty"], round(p["price"] * p["qty"], 2),
                             "、".join("%s %d" % kv for kv in alloc.items()), "%d/%d" % (sum(1 for m in mv if m["status"] == "done"), len(mv)),
                             p["expect_date"], p["note"], G["acc_name"](c, p["created_by"])])
            sheets, fname = [("购入记录", [head] + data, [12, 12, 8, 6, 10, 30, 8, 12, 20, 10])], "购入记录"
        elif kind == "count":
            tid = int(req.q.get("task") or 0)
            sheets, fname = count_report(c, tid), "盘点报告"
        else:
            raise ApiError("类型不正确")
        return {"__file__": xlsx.write(sheets), "filename": "%s_%s.xlsx" % (fname, datetime.date.today().isoformat()),
                "type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}

    # ---------------- 标签
    @route("POST", "/api/asset/labels")
    def api_labels(req):
        need(req, "asset", "finance")
        c, b = req.conn, req.body
        if b.get("ids"):
            ids = [int(x) for x in b["ids"]][:500]
            lst = rows(c, "SELECT * FROM assets WHERE id IN (%s) ORDER BY store, asset_no" % ",".join("?" * len(ids)), ids)
        elif b.get("store"):
            lst = rows(c, "SELECT * FROM assets WHERE store=? AND status IN ('active','transit','pending_in')" + (" AND label_printed=0" if b.get("unprinted") else "") + " ORDER BY asset_no", (b["store"],))
        else:
            lst = rows(c, "SELECT * FROM assets WHERE label_printed=0 AND status IN ('active','transit','pending_in') ORDER BY store, asset_no LIMIT 500")
        smap = store_map(c)
        out = []
        for a in lst:
            m = qr.encode(a["asset_no"])
            out.append({"id": a["id"], "no": a["asset_no"], "name": a["name"], "date": (a["buy_date"] or "")[:7],
                        "store": smap.get(a["store"], a["store"] or ""), "qr": ["".join("1" if v else "0" for v in r) for r in m]})
        if b.get("mark") and out:
            ids = [x["id"] for x in out]
            c.execute("UPDATE assets SET label_printed=1 WHERE id IN (%s)" % ",".join("?" * len(ids)), ids)
            c.commit()
        return {"labels": out}

    # ---------------- 设定
    SECRET_KEYS = ("oss_ak_secret", "ai_key")

    @route("GET", "/api/asset/settings")
    def api_aset(req):
        need(req, "asset")
        c = req.conn
        cfg = settings(c)
        out = {k: cfg.get(k, "") for k in ("asset_no_prefix", "oss_region", "oss_bucket", "oss_ak_id", "ai_model", "stockin_overdue_days")}
        for k in SECRET_KEYS:
            out[k + "_set"] = bool(cfg.get(k))
        pend = one(c, "SELECT COUNT(*) AS n FROM asset_photos WHERE location='pending'")["n"]
        local = one(c, "SELECT COUNT(*) AS n FROM asset_photos WHERE location='local'")["n"]
        return {"settings": out, "demo": bool(G["CFG"].get("demo")), "photos": {"pending": pend, "local": local},
                "items": rows(c, "SELECT * FROM asset_items ORDER BY active DESC, name")}

    @route("POST", "/api/asset/settings")
    def api_aset_save(req):
        need(req, "asset")
        c, b = req.conn, req.body.get("settings") or {}
        if G["CFG"].get("demo") and any(k in b for k in ("oss_ak_id", "oss_ak_secret", "ai_key", "oss_bucket")):
            raise ApiError("演示版不能设定金钥")
        allowed = ("asset_no_prefix", "oss_region", "oss_bucket", "oss_ak_id", "oss_ak_secret", "ai_key", "ai_model", "stockin_overdue_days")
        with Tx(c):
            for k, v in b.items():
                if k not in allowed:
                    continue
                v = str(v).strip()
                if k in SECRET_KEYS and not v:
                    continue          # 空白 = 不修改
                if k == "asset_no_prefix" and not re.match(r"^[A-Za-z0-9]{1,6}$", v):
                    raise ApiError("编号前缀只能是 1–6 个英文字母或数字")
                if k == "stockin_overdue_days" and not v.isdigit():
                    raise ApiError("天数请填数字")
                c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)", (k, v))
            write_log(c, req, "资产设定", "、".join(k for k in b if k in allowed and k not in SECRET_KEYS) or "金钥")
        return {"ok": True}

    @route("POST", "/api/asset/settings/test")
    def api_aset_test(req):
        need(req, "asset")
        c = req.conn
        cfg = settings(c)
        out = {}
        if oss_ready(cfg):
            try:
                oss_put(cfg, "asset/_test.txt", b"ok", "text/plain")
                out["oss"] = "OSS 连线正常"
            except Exception as e:
                out["oss"] = "OSS 连线失败：%s" % str(e)[:100]
        else:
            out["oss"] = "尚未填写 OSS 设定（照片暂存在伺服器）"
        out["ai"] = "已填写 AI 金钥" if cfg.get("ai_key") else "尚未填写 AI 金钥（AI 检测会略过）"
        return out

    # ---------------- 调拨 / 报废 / 入库
    def move_view(c, m, smap):
        d = dict(m)
        a = one(c, "SELECT * FROM assets WHERE id=?", (m["asset_id"],)) or {}
        d.update({"asset_no": a.get("asset_no"), "name": a.get("name"), "price": a.get("price"), "buy_date": a.get("buy_date"),
                  "from_name": smap.get(m["from_store"], m["from_store"] or ""), "to_name": smap.get(m["to_store"], m["to_store"] or ""),
                  "kind_text": MOVE_KIND.get(m["kind"]), "status_text": MOVE_STATUS.get(m["status"]),
                  "created_name": G["acc_name"](c, m["created_by"]),
                  "photos": photos_out(c, jl(m["photos"])), "ship_photos": photos_out(c, jl(m["ship_photos"])),
                  "recv_photos": photos_out(c, jl(m["recv_photos"]))})
        if m["kind"] == "stockin" and m["status"] == "shipped" and m["expect_date"]:
            try:
                od = int(settings(c).get("stockin_overdue_days") or 3)
                d["overdue"] = (datetime.date.today() - datetime.date.fromisoformat(m["expect_date"])).days > od
            except ValueError:
                d["overdue"] = False
        return d

    @route("GET", "/api/asset/moves")
    def api_moves(req):
        need(req, "store", "asset", "finance")
        c, q = req.conn, req.q
        where, args = ["1=1"], []
        if req.me["role"] == "store":
            where.append("(from_store=? OR to_store=?)")
            args += [req.me["code"]] * 2
        if q.get("kind"):
            where.append("kind=?")
            args.append(q["kind"])
        if q.get("status") == "open":
            where.append("status IN ('pending','approved','shipped')")
        elif q.get("status"):
            where.append("status=?")
            args.append(q["status"])
        smap = store_map(c)
        return {"moves": [move_view(c, m, smap) for m in rows(c, "SELECT * FROM asset_moves WHERE %s ORDER BY id DESC LIMIT 500" % " AND ".join(where), args)]}

    def busy_check(c, ids):
        for aid in ids:
            if one(c, "SELECT 1 AS x FROM asset_moves WHERE asset_id=? AND status IN ('pending','approved','shipped')", (aid,)):
                a = one(c, "SELECT asset_no FROM assets WHERE id=?", (aid,))
                raise ApiError("%s 已有进行中的调拨 / 报废 / 入库" % a["asset_no"])

    @route("POST", "/api/asset/request")
    def api_request(req):
        """门店申请调拨（调出 / 调入）或报废。"""
        need(req, "store")
        c, b, me = req.conn, req.body, req.me["code"]
        kind = b.get("kind")
        ids = [int(x) for x in (b.get("ids") or [])]
        if not ids:
            raise ApiError("请选择资产")
        reason = (b.get("reason") or "").strip()[:60]
        note = (b.get("note") or "").strip()[:200]
        with Tx(c):
            busy_check(c, ids)
            created = []
            for aid in ids:
                a = one(c, "SELECT * FROM assets WHERE id=?", (aid,))
                if not a or a["status"] != "active":
                    raise ApiError("资产不存在或不在使用中")
                if kind == "transfer":
                    direction = b.get("dir") or "out"
                    other = b.get("store") or ""
                    if not one(c, "SELECT 1 AS x FROM accounts WHERE code=? AND role='store' AND active=1", (other,)) or other == me:
                        raise ApiError("请选择对方门店")
                    if direction == "out":
                        if a["store"] != me:
                            raise ApiError("只能调出本店资产")
                        fs, ts = me, other
                    else:
                        if a["store"] != other:
                            raise ApiError("资产不属于对方门店")
                        fs, ts = other, me
                    if not reason:
                        raise ApiError("请填写调拨原因")
                    cur = c.execute("""INSERT INTO asset_moves(kind, asset_id, from_store, to_store, status, reason, note, created_by, created_at, expect_date)
                                       VALUES('transfer',?,?,?,'pending',?,?,?,?,?)""", (aid, fs, ts, reason, note, me, now_ms(), b.get("date") or ""))
                    add_event(c, aid, me, "transfer_req", "%s → %s；%s" % (G["acc_name"](c, fs), G["acc_name"](c, ts), reason))
                elif kind == "scrap":
                    if a["store"] != me:
                        raise ApiError("只能报废本店资产")
                    photos = check_photos(c, b.get("photos"), 1)
                    if not reason:
                        raise ApiError("请选择报废原因")
                    cur = c.execute("""INSERT INTO asset_moves(kind, asset_id, from_store, to_store, status, reason, note, photos, created_by, created_at)
                                       VALUES('scrap',?,?,'','pending',?,?,?,?,?)""", (aid, me, reason, note, json.dumps(photos), me, now_ms()))
                    add_event(c, aid, me, "scrap_req", "%s%s" % (reason, "；" + note if note else ""), photos)
                else:
                    raise ApiError("申请类型不正确")
                created.append(cur.lastrowid)
            write_log(c, req, "资产申请", "%s %d 件" % (MOVE_KIND.get(kind), len(ids)))
        return {"ok": True, "created": created}

    def load_move(c, mid):
        m = one(c, "SELECT * FROM asset_moves WHERE id=?", (mid,))
        if not m:
            raise ApiError("记录不存在", 404)
        return m

    @route("POST", r"/api/asset/move/(\d+)/(decide|ship|receive|cancel)")
    def api_move_act(req):
        c, b = req.conn, req.body
        mid, act = int(req.args[0]), req.args[1]
        me, role = req.me["code"], req.me["role"]
        with Tx(c):
            m = load_move(c, mid)
            a = one(c, "SELECT * FROM assets WHERE id=?", (m["asset_id"],))
            t = now_ms()
            if act == "decide":
                need(req, "asset")
                if m["status"] != "pending":
                    raise ApiError("这笔申请已处理", 409)
                ok = bool(b.get("ok"))
                note = (b.get("note") or "").strip()[:200]
                if not ok and not note:
                    raise ApiError("请填写驳回原因")
                if ok and m["asset_id"] in locked_assets(c):
                    raise ApiError("这件资产正在盘点中，盘点结束后才能审批", 409)
                if m["kind"] == "transfer":
                    st = "approved" if ok else "rejected"
                    add_event(c, a["id"], me, "transfer_ok" if ok else "transfer_rej", note)
                else:
                    st = "done" if ok else "rejected"
                    if ok:
                        c.execute("UPDATE assets SET status='scrapped', updated_at=? WHERE id=?", (t, a["id"]))
                    add_event(c, a["id"], me, "scrapped" if ok else "scrap_rej", note)
                c.execute("UPDATE asset_moves SET status=?, decided_by=?, decided_at=?, decide_note=? WHERE id=?", (st, me, t, note, mid))
            elif act == "ship":
                if role != "store" or me != m["from_store"] or m["kind"] != "transfer" or m["status"] != "approved":
                    raise ApiError("现在不能出库", 409)
                photos = check_photos(c, b.get("photos"), 1)
                c.execute("UPDATE asset_moves SET status='shipped', ship_photos=?, ship_at=? WHERE id=?", (json.dumps(photos), t, mid))
                c.execute("UPDATE assets SET status='transit', updated_at=? WHERE id=?", (t, a["id"]))
                add_event(c, a["id"], me, "ship", "出库，送往 %s" % G["acc_name"](c, m["to_store"]), photos)
            elif act == "receive":
                if role != "store" or me != m["to_store"] or m["status"] != "shipped" or m["kind"] not in ("transfer", "stockin"):
                    raise ApiError("现在不能收货", 409)
                refuse = bool(b.get("refuse"))
                note = (b.get("note") or "").strip()[:200]
                photos = check_photos(c, b.get("photos"), 0 if refuse else 1)
                cond = b.get("cond") or "完好"
                if (refuse or cond != "完好") and not note:
                    raise ApiError("请填写说明")
                ai = photo_ai(c, photos)
                c.execute("UPDATE asset_moves SET status=?, recv_photos=?, recv_at=?, recv_cond=?, recv_note=? WHERE id=?",
                          ("refused" if refuse else "done", json.dumps(photos), t, "拒收" if refuse else cond, note, mid))
                ai_txt = {"ok": "AI 符合", "doubt": "AI 存疑", "fail": "AI 不符合"}.get(ai.get("verdict"), "")
                if m["kind"] == "transfer":
                    if refuse:
                        c.execute("UPDATE assets SET status='active', updated_at=? WHERE id=?", (t, a["id"]))
                        add_event(c, a["id"], me, "transfer_refused", note, photos)
                    else:
                        c.execute("UPDATE assets SET status='active', store=?, cond=?, updated_at=? WHERE id=?",
                                  (me, "损坏待修" if cond != "完好" else a["cond"], t, a["id"]))
                        add_event(c, a["id"], me, "receive", "%s；%s%s" % (cond, ai_txt, "；" + note if note else ""), photos)
                else:
                    if refuse:
                        add_event(c, a["id"], me, "stockin_refused", note, photos)
                    else:
                        c.execute("UPDATE assets SET status='active', store=?, cond=?, updated_at=? WHERE id=?",
                                  (me, "损坏待修" if cond == "有损伤" else "正常", t, a["id"]))
                        add_event(c, a["id"], me, "stockin", "%s；%s%s" % (cond, ai_txt, "；" + note if note else ""), photos)
            elif act == "cancel":
                if m["status"] != "pending" or (m["created_by"] != me and role != "asset"):
                    raise ApiError("现在不能撤回", 409)
                c.execute("UPDATE asset_moves SET status='cancelled' WHERE id=?", (mid,))
                add_event(c, a["id"], me, "transfer_cancel" if m["kind"] == "transfer" else "scrap_cancel", "")
            write_log(c, req, "资产%s" % {"decide": "审批", "ship": "出库", "receive": "收货/入库", "cancel": "撤回"}[act],
                      "%s %s" % (MOVE_KIND.get(m["kind"]), a["asset_no"]))
        return {"ok": True}

    @route("POST", "/api/asset/direct")
    def api_direct(req):
        """资产管理员直接调拨 / 报废 / 处理拒收的入库。"""
        need(req, "asset")
        c, b, me = req.conn, req.body, req.me["code"]
        ids = [int(x) for x in (b.get("ids") or [])]
        kind = b.get("kind")
        note = (b.get("note") or "").strip()[:200]
        if not ids:
            raise ApiError("请选择资产")
        with Tx(c):
            busy_check(c, ids)
            lock = locked_assets(c)
            for aid in ids:
                a = one(c, "SELECT * FROM assets WHERE id=?", (aid,))
                if not a or a["status"] not in ("active",):
                    raise ApiError("%s 不在使用中" % (a or {}).get("asset_no", ""))
                if aid in lock:
                    raise ApiError("%s 正在盘点中" % a["asset_no"])
                if kind == "transfer":
                    to = b.get("store") or ""
                    if not one(c, "SELECT 1 AS x FROM accounts WHERE code=? AND role='store' AND active=1", (to,)) or to == a["store"]:
                        raise ApiError("请选择调入门店")
                    c.execute("""INSERT INTO asset_moves(kind, asset_id, from_store, to_store, status, reason, note, created_by, created_at, decided_by, decided_at)
                                 VALUES('transfer',?,?,?,'approved','资产管理员直接调拨',?,?,?,?,?)""", (aid, a["store"], to, note, me, now_ms(), me, now_ms()))
                    add_event(c, aid, me, "transfer_direct", "%s → %s%s" % (G["acc_name"](c, a["store"]), G["acc_name"](c, to), "；" + note if note else ""))
                elif kind == "scrap":
                    if not note:
                        raise ApiError("请填写报废原因")
                    c.execute("UPDATE assets SET status='scrapped', updated_at=? WHERE id=?", (now_ms(), aid))
                    c.execute("""INSERT INTO asset_moves(kind, asset_id, from_store, status, reason, note, created_by, created_at, decided_by, decided_at)
                                 VALUES('scrap',?,?,'done','资产管理员直接报废',?,?,?,?,?)""", (aid, a["store"], note, me, now_ms(), me, now_ms()))
                    add_event(c, aid, me, "scrapped", note)
                else:
                    raise ApiError("类型不正确")
            write_log(c, req, "资产直接%s" % MOVE_KIND.get(kind, ""), "%d 件" % len(ids))
        return {"ok": True}

    @route("POST", "/api/asset/restock")
    def api_restock(req):
        """门店拒收的购入资产：改门店（或同店）重新入库，或直接报废。"""
        need(req, "asset")
        c, b, me = req.conn, req.body, req.me["code"]
        a = one(c, "SELECT * FROM assets WHERE id=?", (int(b.get("id") or 0),))
        if not a or a["status"] != "pending_in":
            raise ApiError("只有待入库的资产能这样处理")
        if one(c, "SELECT 1 AS x FROM asset_moves WHERE asset_id=? AND status IN ('pending','approved','shipped')", (a["id"],)):
            raise ApiError("这件资产已在等待门店入库", 409)
        with Tx(c):
            if b.get("scrap"):
                note = (b.get("note") or "").strip()[:200]
                if not note:
                    raise ApiError("请填写原因")
                c.execute("UPDATE assets SET status='scrapped', updated_at=? WHERE id=?", (now_ms(), a["id"]))
                c.execute("""INSERT INTO asset_moves(kind, asset_id, from_store, status, reason, note, created_by, created_at, decided_by, decided_at)
                             VALUES('scrap',?,?,'done','入库拒收后报废',?,?,?,?,?)""", (a["id"], a["store"], note, me, now_ms(), me, now_ms()))
                add_event(c, a["id"], me, "scrapped", "入库拒收后报废：" + note)
            else:
                st = b.get("store") or a["store"]
                if not one(c, "SELECT 1 AS x FROM accounts WHERE code=? AND role='store' AND active=1", (st,)):
                    raise ApiError("请选择门店")
                c.execute("UPDATE assets SET store=?, updated_at=? WHERE id=?", (st, now_ms(), a["id"]))
                c.execute("""INSERT INTO asset_moves(kind, asset_id, from_store, to_store, status, reason, created_by, created_at, purchase_id, expect_date)
                             VALUES('stockin',?,'',?,'shipped','重新入库',?,?,?,?)""", (a["id"], st, me, now_ms(), a["purchase_id"], ""))
                add_event(c, a["id"], me, "purchase", "重新安排入库：%s" % G["acc_name"](c, st))
            write_log(c, req, "处理拒收资产", a["asset_no"])
        return {"ok": True}

    # ---------------- 财务购入
    @route("POST", "/api/asset/purchase")
    def api_purchase(req):
        need(req, "finance")
        c, b, me = req.conn, req.body, req.me["code"]
        it = item_or_404(c, b.get("item_id"))
        try:
            price = round(float(b.get("price") if b.get("price") not in (None, "") else it["price"]), 2)
        except ValueError:
            raise ApiError("单价请填数字")
        bd = parse_date(b.get("buy_date"))
        if not bd or len(bd) != 10:
            raise ApiError("请选择购入日期")
        ex = b.get("expect_date") or ""
        if ex and not re.match(r"^\d{4}-\d{2}-\d{2}$", ex):
            raise ApiError("预计到货日期不正确")
        alloc = [(x.get("store"), int(x.get("qty") or 0)) for x in (b.get("alloc") or [])]
        alloc = [(s, q) for s, q in alloc if q > 0]
        if not alloc:
            raise ApiError("请分配门店与数量")
        if sum(q for s, q in alloc) > 200:
            raise ApiError("一次最多 200 件")
        for s, q in alloc:
            if not one(c, "SELECT 1 AS x FROM accounts WHERE code=? AND role='store' AND active=1", (s,)):
                raise ApiError("门店不存在")
        qty = sum(q for s, q in alloc)
        note = (b.get("note") or "").strip()[:100]
        with Tx(c):
            cur = c.execute("INSERT INTO purchases(item_id, name, price, qty, buy_date, expect_date, note, created_by, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                            (it["id"], it["name"], price, qty, bd, ex, note, me, now_ms()))
            pid = cur.lastrowid
            nos = next_numbers(c, it["code"], bd[:4], qty)
            ids, k = [], 0
            for s, q in alloc:
                for _ in range(q):
                    no = nos[k]
                    k += 1
                    ac = c.execute("""INSERT INTO assets(asset_no, item_id, name, store, buy_date, price, status, cond, note, purchase_id, created_at, updated_at)
                                      VALUES(?,?,?,?,?,?,'pending_in','正常',?,?,?,?)""", (no, it["id"], it["name"], s, bd, price, note, pid, now_ms(), now_ms()))
                    aid = ac.lastrowid
                    ids.append(aid)
                    c.execute("""INSERT INTO asset_moves(kind, asset_id, from_store, to_store, status, reason, note, created_by, created_at, purchase_id, expect_date)
                                 VALUES('stockin',?,'',?,'shipped','财务购入',?,?,?,?,?)""", (aid, s, note, me, now_ms(), pid, ex))
                    add_event(c, aid, me, "purchase", "¥%g · 分配 %s%s" % (price, G["acc_name"](c, s), "；预计 %s 到货" % ex if ex else ""))
            write_log(c, req, "财务购入", "%s × %d，¥%g" % (it["name"], qty, price))
        return {"ok": True, "purchase": pid, "ids": ids, "nos": nos}

    @route("GET", "/api/asset/fin/home")
    def api_fin_home(req):
        need(req, "finance", "asset")
        c = req.conn
        smap = store_map(c)
        month = datetime.date.today().strftime("%Y-%m")
        ps = rows(c, "SELECT * FROM purchases ORDER BY id DESC LIMIT 200")
        out = []
        for p in ps:
            mv = rows(c, "SELECT * FROM asset_moves WHERE purchase_id=?", (p["id"],))
            alloc = {}
            for m in mv:
                alloc[smap.get(m["to_store"], m["to_store"])] = alloc.get(smap.get(m["to_store"], m["to_store"]), 0) + 1
            p.update({"alloc": alloc, "done": sum(1 for m in mv if m["status"] == "done"), "refused": sum(1 for m in mv if m["status"] == "refused"),
                      "issue": sum(1 for m in mv if m["status"] == "done" and m["recv_cond"] not in ("", "完好")),
                      "notes": [m["recv_note"] for m in mv if m["recv_note"]], "created_name": G["acc_name"](c, p["created_by"])})
            out.append(p)
        mp = [p for p in ps if (p["buy_date"] or "")[:7] == month]
        return {"purchases": out, "month": month, "monthQty": sum(p["qty"] for p in mp),
                "monthAmount": round(sum(p["qty"] * p["price"] for p in mp), 2),
                "pending": one(c, "SELECT COUNT(*) AS n FROM asset_moves WHERE kind='stockin' AND status='shipped'")["n"]}

    # ---------------- 首页
    @route("GET", "/api/asset/store/home")
    def api_store_home(req):
        need(req, "store")
        c, me = req.conn, req.me["code"]
        smap = store_map(c)
        mine = rows(c, "SELECT * FROM assets WHERE store=? AND status IN ('active','transit')", (me,))
        todo = [move_view(c, m, smap) for m in rows(c, """SELECT * FROM asset_moves WHERE
                   (to_store=? AND status='shipped') OR (from_store=? AND kind='transfer' AND status='approved') ORDER BY id""", (me, me))]
        mine_req = [move_view(c, m, smap) for m in rows(c, """SELECT * FROM asset_moves WHERE created_by=? AND
                   (status='pending' OR (status IN ('done','rejected','refused') AND COALESCE(decided_at, recv_at, created_at) > ?)) ORDER BY id DESC LIMIT 20""",
                                                         (me, now_ms() - 7 * 86400000))]
        tasks = store_tasks(c, me)
        return {"count": len(mine), "value": round(sum(a["price"] or 0 for a in mine), 2), "todo": todo, "mine": mine_req, "tasks": tasks}

    @route("GET", "/api/asset/admin/home")
    def api_admin_home(req):
        need(req, "asset")
        c = req.conn
        smap = store_map(c)
        live = rows(c, "SELECT store, price FROM assets WHERE status IN ('active','transit')")
        month0 = int(time.mktime(datetime.date.today().replace(day=1).timetuple()) * 1000)
        pend = [move_view(c, m, smap) for m in rows(c, "SELECT * FROM asset_moves WHERE status='pending' ORDER BY id")]
        overdue = [m for m in (move_view(c, x, smap) for x in rows(c, "SELECT * FROM asset_moves WHERE kind='stockin' AND status='shipped'")) if m.get("overdue")]
        refused = [move_view(c, m, smap) for m in rows(c, "SELECT * FROM asset_moves WHERE kind='stockin' AND status='refused' AND recv_at > ?", (now_ms() - 30 * 86400000,))]
        return {"count": len(live), "stores": len({a["store"] for a in live}), "value": round(sum(a["price"] or 0 for a in live), 2),
                "monthTransfer": one(c, "SELECT COUNT(*) AS n FROM asset_moves WHERE kind='transfer' AND created_at>=?", (month0,))["n"],
                "monthScrap": one(c, "SELECT COUNT(*) AS n FROM asset_moves WHERE kind='scrap' AND status='done' AND decided_at>=?", (month0,))["n"],
                "pending": pend, "overdue": overdue, "refused": refused, "tasks": admin_tasks(c),
                "unprinted": one(c, "SELECT COUNT(*) AS n FROM assets WHERE label_printed=0 AND status IN ('active','transit','pending_in')")["n"],
                "pendingStockin": one(c, "SELECT COUNT(*) AS n FROM asset_moves WHERE kind='stockin' AND status='shipped'")["n"]}

    # ---------------- 盘点（另档）
    import counts
    G["norm_no"], G["next_numbers"] = norm_no, next_numbers
    counts.init(G, sys_helpers={"CONDS": CONDS, "settings": settings, "store_map": store_map, "add_event": add_event, "photos_out": photos_out,
                                "photo_ai": photo_ai, "check_photos": check_photos, "need": need, "jl": jl, "asset_view": asset_view})


def store_tasks(c, store):
    import counts
    return counts.store_tasks(c, store)


def admin_tasks(c):
    import counts
    return counts.admin_tasks(c)


def count_report(c, tid):
    import counts
    return counts.report(c, tid)
