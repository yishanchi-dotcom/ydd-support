# -*- coding: utf-8 -*-
"""不依赖第三方套件的简易 Excel（.xlsx）读写，以及 CSV 读取。"""
import io
import re
import csv
import zipfile
from decimal import Decimal, InvalidOperation
from xml.sax.saxutils import escape
import xml.etree.ElementTree as ET

_BAD = re.compile(u"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _col(n):
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell(ref, v, style=0):
    st = ' s="%d"' % style if style else ""
    if v is None or v == "":
        return '<c r="%s"%s/>' % (ref, st)
    if isinstance(v, bool):
        v = "是" if v else "否"
    if isinstance(v, (int, float)):
        return '<c r="%s"%s><v>%s</v></c>' % (ref, st, repr(v) if isinstance(v, float) else v)
    t = escape(_BAD.sub("", str(v)))
    return '<c r="%s"%s t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % (ref, st, t)


def write(sheets):
    """sheets: [(工作表名称, [[列...], ...], [栏宽...])]，第一列视为标题（粗体、冻结）。回传 bytes。"""
    buf = io.BytesIO()
    z = zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED)
    n = len(sheets)
    z.writestr("[Content_Types].xml",
               '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
               '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
               '<Default Extension="xml" ContentType="application/xml"/>'
               '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
               '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
               + "".join('<Override PartName="/xl/worksheets/sheet%d.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' % (i + 1) for i in range(n))
               + '</Types>')
    z.writestr("_rels/.rels",
               '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
               '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
               '</Relationships>')
    names = []
    for name, _, _ in sheets:
        nm = re.sub(r"[\[\]\*\?/\\:]", "", str(name))[:31] or "Sheet"
        while nm in names:
            nm = nm[:28] + "_%d" % len(names)
        names.append(nm)
    z.writestr("xl/workbook.xml",
               '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
               + "".join('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (escape(nm), i + 1, i + 1) for i, nm in enumerate(names))
               + '</sheets></workbook>')
    z.writestr("xl/_rels/workbook.xml.rels",
               '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
               + "".join('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet%d.xml"/>' % (i + 1, i + 1) for i in range(n))
               + '<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>' % (n + 1)
               + '</Relationships>')
    z.writestr("xl/styles.xml",
               '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
               '<fonts count="2"><font><sz val="11"/><name val="Microsoft YaHei"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Microsoft YaHei"/></font></fonts>'
               '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
               '<fill><patternFill patternType="solid"><fgColor rgb="FF007F61"/></patternFill></fill></fills>'
               '<borders count="1"><border/></borders>'
               '<cellStyleXfs count="1"><xf/></cellStyleXfs>'
               '<cellXfs count="2"><xf/><xf fontId="1" fillId="2" applyFont="1" applyFill="1"/></cellXfs>'
               '</styleSheet>')
    for i, (_, rows, widths) in enumerate(sheets):
        cols = "".join('<col min="%d" max="%d" width="%s" customWidth="1"/>' % (j + 1, j + 1, w) for j, w in enumerate(widths or []))
        body = []
        for r, row in enumerate(rows):
            body.append('<row r="%d">%s</row>' % (r + 1, "".join(_cell(_col(c) + str(r + 1), v, 1 if r == 0 else 0) for c, v in enumerate(row))))
        z.writestr("xl/worksheets/sheet%d.xml" % (i + 1),
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
                   + ("<cols>%s</cols>" % cols if cols else "")
                   + "<sheetData>%s</sheetData></worksheet>" % "".join(body))
    z.close()
    return buf.getvalue()


_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def _num_text(v):
    """把 13800000001.0 / 1.38E+10 之类转为整数字串，避免手机号、编号变形。"""
    try:
        d = Decimal(v)
    except InvalidOperation:
        return v
    if d == d.to_integral_value():
        return str(d.quantize(Decimal(1)))
    return format(d.normalize(), "f")


def read_xlsx(data):
    """读取第一个工作表，回传 [[字串...], ...]。"""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("无法读取：请使用 .xlsx 或 .csv 格式（旧版 .xls 请先另存为 .xlsx）")
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", _NS):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % _NS["m"])))
    sheet_path = "xl/worksheets/sheet1.xml"
    try:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        first = wb.find("m:sheets/m:sheet", _NS)
        rid = first.get(_RNS)
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        for rel in rels:
            if rel.get("Id") == rid:
                tgt = rel.get("Target").lstrip("/")
                sheet_path = tgt if tgt.startswith("xl/") else "xl/" + tgt
    except Exception:
        pass
    root = ET.fromstring(z.read(sheet_path))
    out = []
    for row in root.iter("{%s}row" % _NS["m"]):
        vals = {}
        for c in row.findall("m:c", _NS):
            ref = c.get("r") or ""
            letters = re.match(r"[A-Z]+", ref)
            idx = 0
            if letters:
                for ch in letters.group(0):
                    idx = idx * 26 + (ord(ch) - 64)
                idx -= 1
            else:
                idx = len(vals)
            t = c.get("t")
            v = c.find("m:v", _NS)
            if t == "s" and v is not None:
                val = shared[int(v.text)]
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter("{%s}t" % _NS["m"]))
            elif v is not None and v.text is not None:
                val = v.text if t in ("str", "e") else _num_text(v.text)
            else:
                val = ""
            vals[idx] = str(val).strip()
        if vals:
            out.append([vals.get(i, "") for i in range(max(vals) + 1)])
    return out


def read_csv(data):
    for enc in ("utf-8-sig", "gb18030"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("utf-8", "replace")
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return []
    delim = "\t" if "\t" in lines[0] else ","
    return [[c.strip() for c in r] for r in csv.reader(lines, delimiter=delim)]


def read_text(text):
    """贴上的文字：Tab、逗号或空白分隔。"""
    rows = []
    for l in text.splitlines():
        l = l.strip()
        if not l:
            continue
        if "\t" in l:
            rows.append([c.strip() for c in l.split("\t")])
        elif re.search(u"[,，]", l):
            rows.append([c.strip() for c in re.split(u"[,，]", l)])
        else:
            rows.append(l.split())
    return rows
