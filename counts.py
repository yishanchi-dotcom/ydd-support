"""
资产盘点（v1.3）：发起（范围、品项、全盘 / 抽盘、照片规则、期限）→ 门店拍照盘点（含盘盈、找不到）→ 资产管理员复核 → 结案（盘亏、盘盈入账、状况更新）→ 报告。
"""
import json
import random
import datetime

G = {}
H = {}
CTYPES = ["月度盘点", "季度盘点", "年度盘点", "专项盘点"]
LINE_ST = {"todo": "未盘", "ok": "符合", "doubt": "存疑", "fail": "不符合", "missing": "找不到", "extra": "盘盈"}
REVIEW = {"": "", "pass": "通过", "recount": "退回重盘", "lost": "确认盘亏", "add": "盘盈入账", "ignore": "不处理"}


def one(c, sql, args=()):
    return G["one"](c, sql, args)


def rows(c, sql, args=()):
    return G["rows"](c, sql, args)


def jl(s, d=None):
    try:
        return json.loads(s) if s else (d if d is not None else [])
    except ValueError:
        return d if d is not None else []


def today():
    return datetime.date.today().isoformat()


def task_stores(c, t):
    st = jl(t["stores"], "all")
    if st == "all":
        return [r["store"] for r in rows(c, "SELECT DISTINCT store FROM count_lines WHERE task_id=? ORDER BY store", (t["id"],))]
    return st


def progress(c, tid, store=None):
    w, a = "task_id=?", [tid]
    if store:
        w += " AND store=?"
        a.append(store)
    r = one(c, """SELECT COUNT(*) AS n, SUM(status<>'todo') AS done, SUM(status='ok') AS ok, SUM(status IN ('doubt','fail')) AS doubt,
                  SUM(status='missing') AS missing, SUM(status='extra') AS extra FROM count_lines WHERE %s AND status<>'extra'""" % w, a)
    ex = one(c, "SELECT COUNT(*) AS n FROM count_lines WHERE %s AND status='extra'" % w, a)["n"]
    out = {k: int(r[k] or 0) for k in ("n", "done", "ok", "doubt", "missing")}
    out["extra"] = ex
    return out


def task_view(c, t, smap=None):
    d = dict(t)
    d["rules"] = jl(t["rules"], {})
    d["stores"] = jl(t["stores"], "all")
    d["items"] = jl(t["items"], "all")
    d["summary"] = jl(t["summary"], {})
    d["progress"] = progress(c, t["id"])
    d["overdue"] = t["status"] == "open" and t["end_date"] < today()
    d["status_text"] = {"open": "进行中", "closed": "已结案", "cancelled": "已取消"}.get(t["status"], t["status"])
    return d


def store_tasks(c, store):
    out = []
    for t in rows(c, "SELECT * FROM count_tasks WHERE status='open' ORDER BY end_date"):
        if not one(c, "SELECT 1 AS x FROM count_lines WHERE task_id=? AND store=?", (t["id"], store)):
            continue
        d = task_view(c, t)
        d["progress"] = progress(c, t["id"], store)
        sub = one(c, "SELECT at FROM count_submits WHERE task_id=? AND store=?", (t["id"], store))
        d["submitted"] = sub["at"] if sub else None
        d["recount"] = one(c, "SELECT COUNT(*) AS n FROM count_lines WHERE task_id=? AND store=? AND review='recount' AND status='todo'", (t["id"], store))["n"]
        out.append(d)
    return out


def admin_tasks(c):
    return [task_view(c, t) for t in rows(c, "SELECT * FROM count_tasks WHERE status='open' ORDER BY end_date")]


def report(c, tid):
    t = one(c, "SELECT * FROM count_tasks WHERE id=?", (tid,))
    if not t:
        raise G["ApiError"]("盘点任务不存在")
    smap = H["store_map"](c)
    lines = rows(c, """SELECT l.*, a.asset_no, a.name, a.price, a.buy_date FROM count_lines l LEFT JOIN assets a ON a.id=l.asset_id
                       WHERE l.task_id=? ORDER BY l.store, a.name, a.asset_no""", (tid,))
    by_store = {}
    for l in lines:
        s = by_store.setdefault(l["store"], {"n": 0, "done": 0, "ok": 0, "doubt": 0, "missing": 0, "extra": 0, "lost_value": 0})
        if l["status"] == "extra":
            s["extra"] += 1
            continue
        s["n"] += 1
        s["done"] += l["status"] != "todo"
        s["ok"] += l["status"] == "ok"
        s["doubt"] += l["status"] in ("doubt", "fail")
        s["missing"] += l["status"] == "missing"
        if l["review"] == "lost":
            s["lost_value"] += l["price"] or 0
    sum_rows = [["门店编号", "门店", "应盘", "已盘", "符合", "存疑", "找不到", "盘盈", "盘亏金额", "完成率"]]
    for k in sorted(by_store):
        s = by_store[k]
        sum_rows.append([k, smap.get(k, k), s["n"], s["done"], s["ok"], s["doubt"], s["missing"], s["extra"], round(s["lost_value"], 2),
                         "%d%%" % (100 * s["done"] / s["n"]) if s["n"] else "-"])
    det = [["门店", "资产编号", "资产名称", "购入时间", "价格", "盘点结果", "状况", "AI 判定", "门店说明", "复核", "复核说明", "盘点时间"]]
    for l in lines:
        ai = jl(l["ai"], {})
        det.append([smap.get(l["store"], l["store"]), l["asset_no"] or l["extra_no"], l["name"] or l["extra_name"], l["buy_date"] or "",
                    l["price"] or "", LINE_ST.get(l["status"]), l["cond"], {"ok": "符合", "doubt": "存疑", "fail": "不符合", "skip": "未检测"}.get(ai.get("verdict"), ""),
                    l["note"], REVIEW.get(l["review"] or "", l["review"]), l["review_note"], G["fmt_ts"](l["at"])])
    info = [["项目", "内容"], ["任务", t["name"]], ["类型", t["ctype"]], ["期间", "%s ～ %s" % (t["start_date"], t["end_date"])],
            ["状态", {"open": "进行中", "closed": "已结案", "cancelled": "已取消"}.get(t["status"])], ["结案时间", G["fmt_ts"](t["closed_at"])]]
    return [("汇总", sum_rows, [10, 14, 8, 8, 8, 8, 8, 8, 10, 8]), ("明细", det, [12, 18, 12, 10, 8, 10, 10, 8, 24, 10, 20, 16]), ("任务资讯", info, [12, 40])]


def init(g, sys_helpers):
    G.update(g)
    H.update(sys_helpers)
    route, Tx, write_log, ApiError, now_ms = g["route"], g["Tx"], g["write_log"], g["ApiError"], g["now_ms"]
    need = H["need"]

    def scope_assets(c, stores, items):
        w, a = ["status='active'"], []
        if stores != "all":
            w.append("store IN (%s)" % ",".join("?" * len(stores)))
            a += stores
        if items != "all":
            w.append("item_id IN (%s)" % ",".join("?" * len(items)))
            a += items
        return rows(c, "SELECT * FROM assets WHERE %s ORDER BY store, asset_no" % " AND ".join(w), a)

    def parse_task(c, b):
        name = (b.get("name") or "").strip()[:40]
        if not name:
            raise ApiError("请填写任务名称")
        ctype = b.get("ctype") if b.get("ctype") in CTYPES else "专项盘点"
        stores = b.get("stores") if b.get("stores") == "all" else [str(x) for x in (b.get("stores") or [])]
        items = b.get("items") if b.get("items") == "all" else [int(x) for x in (b.get("items") or [])]
        if stores != "all" and not stores:
            raise ApiError("请选择门店")
        if items != "all" and not items:
            raise ApiError("请选择品项")
        mode = b.get("mode") if b.get("mode") in ("full", "sample") else "full"
        try:
            pct = max(5, min(100, int(b.get("pct") or 20)))
        except ValueError:
            pct = 20
        rules = {"photo": b.get("photo") if b.get("photo") in ("each", "label", "none") else "each",
                 "ai": bool(b.get("ai", True)), "pct": pct, "remind": bool(b.get("remind", True)),
                 "lock": bool(b.get("lock", True)), "note": (b.get("note") or "")[:200]}
        sd, ed = b.get("start_date") or today(), b.get("end_date") or ""
        rd = b.get("review_date") or ed
        try:
            for d in (sd, ed, rd):
                datetime.date.fromisoformat(d)
        except ValueError:
            raise ApiError("请填写正确的日期")
        if ed < sd:
            raise ApiError("截止日期不能早于开始日期")
        if rd < ed:
            raise ApiError("复核日期不能早于门店截止日期")
        return {"name": name, "ctype": ctype, "stores": stores, "items": items, "mode": mode, "rules": rules,
                "start_date": sd, "end_date": ed, "review_date": rd}

    def pick(lst, mode, pct):
        if mode == "full":
            return lst
        by = {}
        for a in lst:
            by.setdefault(a["store"], []).append(a)
        out = []
        rnd = random.Random()
        for s, l in by.items():
            k = max(1, round(len(l) * pct / 100.0))
            out += rnd.sample(l, min(k, len(l)))
        return out

    @route("POST", "/api/asset/count/preview")
    def api_count_preview(req):
        need(req, "asset")
        c = req.conn
        p = parse_task(c, dict(req.body, name=req.body.get("name") or "x", end_date=req.body.get("end_date") or today()))
        lst = scope_assets(c, p["stores"], p["items"])
        smap = H["store_map"](c)
        per = {}
        for a in lst:
            per[a["store"]] = per.get(a["store"], 0) + 1
        pct = p["rules"]["pct"]
        busy = one(c, "SELECT COUNT(*) AS n FROM asset_moves WHERE status IN ('pending','approved','shipped') AND kind<>'stockin'")["n"]
        return {"total": len(lst), "sampled": sum(max(1, round(n * pct / 100.0)) for n in per.values()) if p["mode"] == "sample" else len(lst),
                "stores": [{"store": k, "name": smap.get(k, k), "n": v} for k, v in sorted(per.items())], "busyMoves": busy}

    @route("POST", "/api/asset/count")
    def api_count_create(req):
        need(req, "asset")
        c, me = req.conn, req.me["code"]
        p = parse_task(c, req.body)
        lst = pick(scope_assets(c, p["stores"], p["items"]), p["mode"], p["rules"]["pct"])
        if not lst:
            raise ApiError("范围内没有在用资产")
        with Tx(c):
            cur = c.execute("""INSERT INTO count_tasks(name, ctype, stores, items, mode, rules, start_date, end_date, review_date, status, created_by, created_at)
                               VALUES(?,?,?,?,?,?,?,?,?,'open',?,?)""",
                            (p["name"], p["ctype"], json.dumps(p["stores"]), json.dumps(p["items"]), p["mode"], json.dumps(p["rules"], ensure_ascii=False),
                             p["start_date"], p["end_date"], p["review_date"], me, now_ms()))
            tid = cur.lastrowid
            c.executemany("INSERT INTO count_lines(task_id, asset_id, store, status) VALUES(?,?,?,'todo')", [(tid, a["id"], a["store"]) for a in lst])
            write_log(c, req, "发起盘点", "%s：%d 件、%d 店" % (p["name"], len(lst), len({a["store"] for a in lst})))
        return {"ok": True, "id": tid, "n": len(lst)}

    @route("GET", "/api/asset/counts")
    def api_counts(req):
        need(req, "asset", "store")
        c = req.conn
        if req.me["role"] == "store":
            return {"tasks": store_tasks(c, req.me["code"]),
                    "history": [task_view(c, t) for t in rows(c, """SELECT * FROM count_tasks WHERE status='closed' AND id IN
                                (SELECT task_id FROM count_lines WHERE store=?) ORDER BY id DESC LIMIT 20""", (req.me["code"],))]}
        return {"tasks": [task_view(c, t) for t in rows(c, "SELECT * FROM count_tasks ORDER BY CASE status WHEN 'open' THEN 0 ELSE 1 END, id DESC LIMIT 100")]}

    def line_view(c, l, sec=None):
        d = dict(l)
        a = one(c, "SELECT asset_no, name, price, buy_date, cond AS asset_cond, item_id FROM assets WHERE id=?", (l["asset_id"],)) if l["asset_id"] else None
        d.update(a or {"asset_no": l["extra_no"], "name": l["extra_name"], "price": None, "buy_date": "", "asset_cond": "", "item_id": None})
        d["ai"] = jl(l["ai"], {})
        d["photos"] = H["photos_out"](c, [l["photo"]] if l["photo"] else [])
        d["status_text"] = LINE_ST.get(l["status"])
        d["review_text"] = REVIEW.get(l["review"] or "", "")
        return d

    def load_task(c, tid):
        t = one(c, "SELECT * FROM count_tasks WHERE id=?", (tid,))
        if not t:
            raise ApiError("盘点任务不存在", 404)
        return t

    @route("GET", "/api/asset/count/detail")
    def api_count_detail(req):
        need(req, "asset", "store")
        c = req.conn
        t = load_task(c, int(req.q.get("id") or 0))
        smap = H["store_map"](c)
        if req.me["role"] == "store":
            st = req.me["code"]
        else:
            st = req.q.get("store") or ""
        out = {"task": task_view(c, t)}
        if st:
            lines = rows(c, """SELECT l.* FROM count_lines l LEFT JOIN assets a ON a.id=l.asset_id WHERE l.task_id=? AND l.store=?
                               ORDER BY CASE l.status WHEN 'todo' THEN 0 ELSE 1 END, a.name, a.asset_no""", (t["id"], st))
            if req.me["role"] == "store" and not lines:
                raise ApiError("本店不在这次盘点范围内", 404)
            out["lines"] = [line_view(c, l) for l in lines]
            out["store"] = {"code": st, "name": smap.get(st, st)}
            out["progress"] = progress(c, t["id"], st)
            sub = one(c, "SELECT at FROM count_submits WHERE task_id=? AND store=?", (t["id"], st))
            out["submitted"] = sub["at"] if sub else None
        if req.me["role"] == "asset":
            sts = []
            for s in task_stores(c, t):
                pr = progress(c, t["id"], s)
                sub = one(c, "SELECT at FROM count_submits WHERE task_id=? AND store=?", (t["id"], s))
                pend = one(c, "SELECT COUNT(*) AS n FROM count_lines WHERE task_id=? AND store=? AND status IN ('doubt','fail','missing','extra') AND review=''", (t["id"], s))["n"]
                sts.append({"store": s, "name": smap.get(s, s), "progress": pr, "submitted": sub["at"] if sub else None, "toReview": pend})
            out["stores"] = sts
            out["toReview"] = sum(x["toReview"] for x in sts)
        return out

    def open_task_for_store(c, tid, store):
        t = load_task(c, tid)
        if t["status"] != "open":
            raise ApiError("这次盘点已结束", 409)
        if t["start_date"] > today():
            raise ApiError("盘点尚未开始（%s 开始）" % t["start_date"], 409)
        return t

    @route("POST", "/api/asset/count/line")
    def api_count_line(req):
        """门店盘点一件：found（拍照）/ missing（找不到）。"""
        need(req, "store")
        c, b, me = req.conn, req.body, req.me["code"]
        l = one(c, "SELECT * FROM count_lines WHERE id=?", (int(b.get("id") or 0),))
        if not l or l["store"] != me:
            raise ApiError("资料不存在", 404)
        t = open_task_for_store(c, l["task_id"], me)
        if one(c, "SELECT 1 AS x FROM count_submits WHERE task_id=? AND store=?", (t["id"], me)) and l["review"] != "recount":
            raise ApiError("本店已提交，不能再修改；如需更正请联络资产管理员", 409)
        rules = jl(t["rules"], {})
        note = (b.get("note") or "").strip()[:200]
        if b.get("missing"):
            if not note:
                raise ApiError("请说明找不到的原因")
            st, cond, photo, ai = "missing", "", "", {}
        else:
            cond = b.get("cond") if b.get("cond") in H["CONDS"] else "正常"
            photos = b.get("photos") or []
            if rules.get("photo", "each") != "none":
                photos = H["check_photos"](c, photos, 1)
            photo = photos[0] if photos else ""
            ai = H["photo_ai"](c, [photo]) if photo and rules.get("ai", True) else {"verdict": "skip"}
            st = {"ok": "ok", "skip": "ok", "doubt": "doubt", "fail": "fail"}.get(ai.get("verdict"), "ok")
            if cond == "损坏待修" and st == "ok":
                st = "doubt"
            if st != "ok" and not note and ai.get("verdict") in ("doubt", "fail"):
                note = ""
        with Tx(c):
            c.execute("UPDATE count_lines SET status=?, cond=?, photo=?, ai=?, note=?, at=?, review=CASE review WHEN 'recount' THEN '' ELSE review END WHERE id=?",
                      (st, cond, photo, json.dumps(ai, ensure_ascii=False), note, now_ms(), l["id"]))
        return {"ok": True, "status": st, "ai": ai}

    @route("POST", "/api/asset/count/extra")
    def api_count_extra(req):
        """盘盈：店里有、但清单上没有的资产。"""
        need(req, "store")
        c, b, me = req.conn, req.body, req.me["code"]
        t = open_task_for_store(c, int(b.get("task") or 0), me)
        name = (b.get("name") or "").strip()[:40]
        if not name:
            raise ApiError("请选择资产名称")
        photos = H["check_photos"](c, b.get("photos"), 1)
        no = G["norm_no"](b.get("no") or "")
        with Tx(c):
            c.execute("""INSERT INTO count_lines(task_id, asset_id, store, status, cond, photo, ai, note, at, extra_name, extra_no)
                         VALUES(?,?,?,'extra',?,?,?,?,?,?,?)""",
                      (t["id"], None, me, b.get("cond") if b.get("cond") in H["CONDS"] else "正常", photos[0],
                       json.dumps(H["photo_ai"](c, photos), ensure_ascii=False), (b.get("note") or "")[:200], now_ms(), name, no))
        return {"ok": True}

    @route("POST", "/api/asset/count/extra/delete")
    def api_count_extra_del(req):
        need(req, "store")
        c, me = req.conn, req.me["code"]
        l = one(c, "SELECT * FROM count_lines WHERE id=? AND status='extra' AND store=?", (int(req.body.get("id") or 0), me))
        if not l:
            raise ApiError("资料不存在")
        open_task_for_store(c, l["task_id"], me)
        if one(c, "SELECT 1 AS x FROM count_submits WHERE task_id=? AND store=?", (l["task_id"], me)):
            raise ApiError("本店已提交", 409)
        c.execute("DELETE FROM count_lines WHERE id=?", (l["id"],))
        c.commit()
        return {"ok": True}

    @route("POST", "/api/asset/count/submit")
    def api_count_submit(req):
        need(req, "store")
        c, me = req.conn, req.me["code"]
        t = open_task_for_store(c, int(req.body.get("task") or 0), me)
        left = one(c, "SELECT COUNT(*) AS n FROM count_lines WHERE task_id=? AND store=? AND status='todo'", (t["id"], me))["n"]
        if left:
            raise ApiError("还有 %d 件未盘点" % left)
        with Tx(c):
            c.execute("INSERT OR REPLACE INTO count_submits(task_id, store, at) VALUES(?,?,?)", (t["id"], me, now_ms()))
            write_log(c, req, "提交盘点", t["name"])
        return {"ok": True}

    @route("POST", "/api/asset/count/review")
    def api_count_review(req):
        """资产管理员复核：pass / recount / lost / add / ignore。"""
        need(req, "asset")
        c, b = req.conn, req.body
        ids = [int(x) for x in (b.get("ids") or [])]
        act = b.get("act")
        if act not in ("pass", "recount", "lost", "add", "ignore"):
            raise ApiError("动作不正确")
        note = (b.get("note") or "").strip()[:200]
        if act == "recount" and not note:
            raise ApiError("请填写退回原因，门店会看到")
        with Tx(c):
            for i in ids:
                l = one(c, "SELECT * FROM count_lines WHERE id=?", (i,))
                if not l:
                    continue
                t = load_task(c, l["task_id"])
                if t["status"] != "open":
                    raise ApiError("这次盘点已结案", 409)
                if act == "add" and l["status"] != "extra":
                    raise ApiError("只有盘盈项目能入账")
                if act == "lost" and l["status"] != "missing":
                    raise ApiError("只有「找不到」的项目能确认盘亏")
                if act == "recount":
                    if l["status"] == "extra":
                        raise ApiError("盘盈项目不能退回重盘，可选不处理")
                    c.execute("UPDATE count_lines SET status='todo', review='recount', review_note=? WHERE id=?", (note, i))
                    c.execute("DELETE FROM count_submits WHERE task_id=? AND store=?", (l["task_id"], l["store"]))
                else:
                    c.execute("UPDATE count_lines SET review=?, review_note=? WHERE id=?", (act, note, i))
            write_log(c, req, "盘点复核", "%s %d 件" % (REVIEW[act], len(ids)))
        return {"ok": True}

    @route("POST", "/api/asset/count/close")
    def api_count_close(req):
        need(req, "asset")
        c, b, me = req.conn, req.body, req.me["code"]
        t = load_task(c, int(b.get("id") or 0))
        if t["status"] != "open":
            raise ApiError("这次盘点已结束", 409)
        if b.get("cancel"):
            with Tx(c):
                c.execute("UPDATE count_tasks SET status='cancelled', closed_at=? WHERE id=?", (now_ms(), t["id"]))
                write_log(c, req, "取消盘点", t["name"])
            return {"ok": True}
        opts = b.get("opts") or {}
        todo_act = opts.get("todo") or "keep"       # 未盘：keep 维持在用 / lost 视为盘亏
        pending = one(c, "SELECT COUNT(*) AS n FROM count_lines WHERE task_id=? AND status IN ('missing','extra') AND review=''", (t["id"],))["n"]
        if pending and not opts.get("force"):
            raise ApiError("还有 %d 笔「找不到 / 盘盈」未复核" % pending, 409)
        pr = progress(c, t["id"])
        lost_n, lost_v, added, cond_n = 0, 0.0, 0, 0
        smap = H["store_map"](c)
        with Tx(c):
            for l in rows(c, "SELECT * FROM count_lines WHERE task_id=?", (t["id"],)):
                if l["asset_id"]:
                    a = one(c, "SELECT * FROM assets WHERE id=?", (l["asset_id"],))
                    if not a:
                        continue
                    lost = l["review"] == "lost" or (l["status"] == "todo" and todo_act == "lost")
                    if lost and a["status"] == "active":
                        c.execute("UPDATE assets SET status='lost', updated_at=? WHERE id=?", (now_ms(), a["id"]))
                        H["add_event"](c, a["id"], me, "lost", "%s：%s" % (t["name"], l["note"] or l["review_note"] or "未盘到"))
                        lost_n += 1
                        lost_v += a["price"] or 0
                    elif l["status"] in ("ok", "doubt", "fail"):
                        H["add_event"](c, a["id"], l["store"], "count", "%s：%s%s" % (t["name"], LINE_ST[l["status"]], "；" + l["cond"] if l["cond"] else ""),
                                       [l["photo"]] if l["photo"] else [])
                        if l["cond"] and l["cond"] != a["cond"]:
                            c.execute("UPDATE assets SET cond=?, updated_at=? WHERE id=?", (l["cond"], now_ms(), a["id"]))
                            cond_n += 1
                elif l["status"] == "extra" and l["review"] == "add":
                    it = one(c, "SELECT * FROM asset_items WHERE name=?", (l["extra_name"],))
                    if not it:
                        continue
                    no = l["extra_no"]
                    if not no or one(c, "SELECT 1 AS x FROM assets WHERE asset_no=?", (no,)):
                        no = G["next_numbers"](c, it["code"], today()[:4], 1)[0]
                    cur = c.execute("""INSERT INTO assets(asset_no, item_id, name, store, buy_date, price, status, cond, note, created_at, updated_at)
                                       VALUES(?,?,?,?,'',?,'active',?,?,?,?)""", (no, it["id"], it["name"], l["store"], it["price"], l["cond"] or "正常",
                                                                               "盘盈：" + t["name"], now_ms(), now_ms()))
                    H["add_event"](c, cur.lastrowid, me, "found", "%s；%s" % (t["name"], smap.get(l["store"], l["store"])), [l["photo"]] if l["photo"] else [])
                    c.execute("UPDATE count_lines SET asset_id=? WHERE id=?", (cur.lastrowid, l["id"]))
                    added += 1
            summary = {"n": pr["n"], "done": pr["done"], "ok": pr["ok"], "doubt": pr["doubt"], "missing": pr["missing"], "extra": pr["extra"],
                       "lost": lost_n, "lostValue": round(lost_v, 2), "added": added, "condChanged": cond_n}
            c.execute("UPDATE count_tasks SET status='closed', closed_at=?, summary=? WHERE id=?", (now_ms(), json.dumps(summary), t["id"]))
            write_log(c, req, "盘点结案", "%s：盘亏 %d、盘盈入账 %d" % (t["name"], lost_n, added))
        return {"ok": True, "summary": summary}
