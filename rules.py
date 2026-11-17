# -*- coding: utf-8 -*-
"""
工时与补贴计算规则（v1.2 定案，见专案文件「v1.2需求-工时与补贴」）。
所有时间以「分钟」计算，结束时间可超过 24:00（次日）。
"""
import math
import json
import time
import datetime
import urllib.request
import urllib.parse

NON_ITEMS = ["开会", "大扫除", "开业前筹备", "培训"]
SPECIALS = ["延长营业"] + NON_ITEMS + ["其他"]
DAY_NAMES = ["周日", "周一", "周二", "周三", "周四", "周五", "周六", "法定节假日"]
MAX_END = 30 * 60      # 结束时间最晚到次日 06:00


def tmin(t):
    h, m = str(t).split(":")
    return int(h) * 60 + int(m)


def tlabel(m):
    m = int(m)
    if m > 1440:
        return "次日%02d:%02d" % ((m - 1440) // 60, m % 60)
    return "%02d:%02d" % (m // 60, m % 60)


def haversine_km(lat1, lng1, lat2, lng2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def wgs84_to_gcj02(lat, lng):
    """手机 GPS（WGS84）转高德坐标（GCJ-02）。"""
    a, ee = 6378245.0, 0.00669342162296594323
    x, y = lng - 105.0, lat - 35.0
    dlat = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    dlat += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    dlat += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    dlat += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    dlng = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    dlng += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    dlng += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    dlng += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    rad = lat / 180.0 * math.pi
    magic = 1 - ee * math.sin(rad) ** 2
    sq = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sq) * math.pi)
    dlng = (dlng * 180.0) / (a / sq * math.cos(rad) * math.pi)
    return lat + dlat, lng + dlng


_FAIL = {"until": 0, "msg": ""}   # 高德连线失败后 5 分钟内不再尝试，避免每次发起都卡住


def amap_driving_km(key, lat1, lng1, lat2, lng2, timeout=6):
    """高德 Web 服务「距离测量」type=1（驾车）。失败回传 (None, 错误说明)。"""
    if time.time() < _FAIL["until"]:
        return None, _FAIL["msg"]
    km, err = _amap_driving_km(key, lat1, lng1, lat2, lng2, timeout)
    if km is None:
        _FAIL.update(until=time.time() + 300, msg=err)
    return km, err


def _amap_driving_km(key, lat1, lng1, lat2, lng2, timeout):
    q = urllib.parse.urlencode({"origins": "%.6f,%.6f" % (lng1, lat1), "destination": "%.6f,%.6f" % (lng2, lat2),
                                "type": "1", "key": key, "output": "JSON"})
    try:
        with urllib.request.urlopen("https://restapi.amap.com/v3/distance?" + q, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return None, "无法连线高德：%s" % e
    if str(d.get("status")) != "1" or not d.get("results"):
        return None, "高德回传错误：%s" % (d.get("info") or "未知")
    try:
        return round(float(d["results"][0]["distance"]) / 1000.0, 1), ""
    except (KeyError, ValueError, TypeError):
        return None, "高德回传格式不正确"


def load_settings(c):
    from db import SETTING_DEFAULTS, SETTING_DEFAULTS_V4
    cfg = dict(SETTING_DEFAULTS)
    cfg.update(SETTING_DEFAULTS_V4)
    for r in c.execute("SELECT key, value FROM settings"):
        cfg[r["key"]] = r["value"]
    return cfg


def holiday_name(c, date):
    r = c.execute("SELECT name FROM holidays WHERE date=?", (date,)).fetchone()
    return r["name"] if r else ""


def store_hours(c, store):
    return [dict(r) for r in c.execute("SELECT * FROM store_hours WHERE store=? ORDER BY sort, id", (store,))]


def hours_for(c, store, date):
    """回传当天适用的营业时间 {open, close, label}；未设定回传 None。后设的规则优先。"""
    rules = store_hours(c, store)
    if not rules:
        return None
    d = datetime.date.fromisoformat(date)
    wd = (d.weekday() + 1) % 7            # 0=周日
    is_hol = bool(holiday_name(c, date))
    hit, label = None, ""
    for r in rules:
        days = [int(x) for x in r["days"].split(",") if x != ""]
        if not days:
            if hit is None:
                hit, label = r, "每天"
        elif wd in days or (is_hol and 7 in days):
            hit, label = r, "、".join(DAY_NAMES[x] for x in days)
    if hit is None:
        return None
    return {"open": tmin(hit["open_time"]), "close": tmin(hit["close_time"]), "label": label}


def pair(a, b):
    return (a, b) if a < b else (b, a)


def distance_info(c, a, b, cfg=None, allow_fetch=True):
    """
    两店距离（公里）与来源。顺序：人资手动 / 已快取 → 驾车（高德）→ 直线。
    回传 {"km", "source"}；任一方没有定位则回传 None。
    """
    if a == b:
        return None
    x, y = pair(a, b)
    row = c.execute("SELECT km, source FROM store_distances WHERE a=? AND b=?", (x, y)).fetchone()
    if row:
        return {"km": row["km"], "source": row["source"]}
    ra = c.execute("SELECT lat, lng FROM accounts WHERE code=?", (a,)).fetchone()
    rb = c.execute("SELECT lat, lng FROM accounts WHERE code=?", (b,)).fetchone()
    if not ra or not rb or ra["lat"] is None or rb["lat"] is None:
        return None
    cfg = cfg or load_settings(c)
    straight = round(haversine_km(ra["lat"], ra["lng"], rb["lat"], rb["lng"]), 1)
    if cfg.get("dist_mode") == "driving" and cfg.get("amap_ws_key") and allow_fetch:
        km, err = amap_driving_km(cfg["amap_ws_key"], ra["lat"], ra["lng"], rb["lat"], rb["lng"])
        if km is not None:
            c.execute("INSERT OR REPLACE INTO store_distances(a, b, km, source, updated_at) VALUES(?,?,?,?,?)",
                      (x, y, km, "driving", int(time.time() * 1000)))
            return {"km": km, "source": "driving"}
        return {"km": straight, "source": "straight", "error": err}   # 暂时失败：本次用直线，不快取，下次再试
    c.execute("INSERT OR REPLACE INTO store_distances(a, b, km, source, updated_at) VALUES(?,?,?,?,?)",
              (x, y, straight, "straight", int(time.time() * 1000)))
    return {"km": straight, "source": "straight"}


def distance_km(c, a, b, cfg=None):
    d = distance_info(c, a, b, cfg)
    return d["km"] if d else None


SOURCE_NAMES = {"driving": "驾车距离", "straight": "直线距离"}


def long_override(c, a, b):
    """人资指定：True 长途 / False 非长途 / None 依距离自动判断。"""
    if a == b:
        return None
    row = c.execute("SELECT is_long FROM long_overrides WHERE a=? AND b=?", pair(a, b)).fetchone()
    return None if row is None else bool(row["is_long"])


def is_hq(c, code):
    r = c.execute("SELECT role FROM accounts WHERE code=?", (code,)).fetchone()
    return bool(r and r["role"] == "hq")


def compute(c, r, cfg=None):
    """
    r 需要：date, start_time, end_time, from_store, to_store, nature, special
    回传要写进 requests 的计算栏位，另含 notes（说明）与 bh（当天营业时间）。
    """
    cfg = cfg or load_settings(c)
    s, e = tmin(r["start_time"]), tmin(r["end_time"])
    hol = holiday_name(c, r["date"])
    nature = r.get("nature") or "op"
    special = r.get("special") or ""
    to_hq = is_hq(c, r["to_store"])
    notes = []
    lunch = 0
    if to_hq:
        nature, special = "non", "开会"
        # 总部（办公室）跨到午休时段，重叠部分不计工时
        lunch = max(0, min(e, tmin(cfg["hq_lunch_end"])) - max(s, tmin(cfg["hq_lunch_start"])))
    h = max(0, e - s - lunch) / 60.0
    if lunch:
        notes.append("总部午休 %s–%s 扣除 %g 小时" % (cfg["hq_lunch_start"], cfg["hq_lunch_end"], lunch / 60.0))
    if special in NON_ITEMS:
        nature = "non"
    bh = None if to_hq else hours_for(c, r["to_store"], r["date"])
    prep, clean = int(cfg["prep_min"]), int(cfg["clean_min"])
    out = bool(bh) and (s < bh["open"] - prep or e > bh["close"] + clean)
    op = non = night_h = 0.0
    if nature == "op":
        op = h
        non = h * 2 if hol else 0.0
        notes.append("%s：营运 %g + 非营运 %g 小时（三倍薪）" % (hol, op, non) if hol else "营运工时 %g 小时" % op)
        if bh:
            ns = tmin(cfg["night_start"])
            lim = e if special == "延长营业" else min(e, bh["close"])
            ov = lim - max(s, ns)
            if ov > 0:
                night_h = math.ceil(ov / 30.0) / 2.0
                notes.append("夜班 %s–%s 共 %g 小时" % (tlabel(max(s, ns)), tlabel(lim), night_h))
    else:
        non = h * (3 if hol else 1)
        notes.append("非营运%s %g 小时%s" % ("（%s）" % special if special else "", h, "，%s × 3" % hol if hol else ""))
    di = distance_info(c, r["from_store"], r["to_store"], cfg)
    km = di["km"] if di else None
    ov = long_override(c, r["from_store"], r["to_store"])
    long_on = ov if ov is not None else (km is not None and km >= float(cfg["long_km"]))
    long_pay = h * float(cfg["long_pay"]) if long_on else 0.0
    if di:
        notes.append("两店%s约 %g 公里" % (SOURCE_NAMES.get(di["source"], ""), km))
    if ov is not None:
        notes.append("人资指定为%s" % ("长途" if ov else "非长途"))
    elif long_on:
        notes.append("长途")
    return {
        "nature": nature, "special": special, "holiday": hol, "hours": h,
        "op_hours": op, "non_hours": non, "night_hours": night_h,
        "night_pay": night_h * float(cfg["night_pay"]), "long_km": km, "long_pay": long_pay,
        "out_of_hours": 1 if out else 0, "payer": r["to_store"],
        "notes": notes, "bh": ({"open": tlabel(bh["open"]), "close": tlabel(bh["close"]), "label": bh["label"],
                                "from": tlabel(bh["open"] - prep), "to": tlabel(bh["close"] + clean)} if bh else None),
        "to_hq": to_hq, "lunch_hours": lunch / 60.0,
        "dist_source": di["source"] if di else None, "long_override": ov, "dist_error": (di or {}).get("error", ""),
    }


CALC_COLS = ["nature", "special", "holiday", "op_hours", "non_hours", "night_hours", "night_pay", "long_km", "long_pay", "out_of_hours", "payer"]
