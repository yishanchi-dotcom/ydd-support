// 1点点 资产管理模块（v1.3）— 门店 / 资产管理员 / 财务 画面
(() => {
"use strict";
let api, run, shell, ask, openSheet, closeSheet, toast, esc, fmt, go, download, qparam, ts, today, yen, $, me, accName;
let META = null;

const CSS = `
.ast{display:inline-block;border-radius:6px;padding:1px 8px;font-size:12px;font-weight:700;white-space:nowrap}
.ast.active,.ast.ok,.ast.done{background:var(--gl);color:var(--g2)}.ast.transit,.ast.shipped,.ast.approved,.ast.pending_in{background:var(--bluel);color:var(--blue)}
.ast.pending,.ast.doubt,.ast.todo{background:var(--al);color:#7a5200}.ast.scrapped,.ast.cancelled,.ast.rejected,.ast.skip{background:#EEF0EF;color:var(--mute)}
.ast.lost,.ast.fail,.ast.missing,.ast.refused{background:var(--redl);color:var(--red)}.ast.extra{background:#F0EBFB;color:#6D4BC4}
.al{display:flex;gap:10px;align-items:center;padding:11px 2px;border-bottom:1px solid var(--line);cursor:pointer}
.al:last-child{border-bottom:0}.al .t{flex:1;min-width:0}.al .t b{display:block;font-size:15px}.al .t small{display:block;font-size:12px;color:var(--mute);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.al .th{width:46px;height:46px;border-radius:10px;background:var(--bg);flex:none;object-fit:cover;border:1px solid var(--line)}
.al .ck{flex:none}
.phs{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0}
.phs .p{position:relative;width:78px;height:78px;border-radius:12px;overflow:hidden;border:1px solid var(--line);background:#fff}
.phs .p img{width:100%;height:100%;object-fit:cover;display:block}
.phs .p .v{position:absolute;left:0;right:0;bottom:0;font-size:11px;text-align:center;color:#fff;padding:1px 0;font-weight:700}
.phs .p .v.ok{background:#007F61dd}.phs .p .v.doubt{background:#d18a00dd}.phs .p .v.fail{background:#C8402Fdd}.phs .p .v.skip{background:#6B7A76cc}
.phs .p .x{position:absolute;top:2px;right:2px;width:22px;height:22px;border-radius:11px;border:0;background:#0008;color:#fff;font-size:13px;line-height:1;cursor:pointer}
.phs .add{width:78px;height:78px;border-radius:12px;border:1.5px dashed var(--g);background:var(--gl);color:var(--g);font:inherit;font-size:13px;font-weight:700;cursor:pointer;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px}
.phs .add i{font-style:normal;font-size:22px;line-height:1}
.aimsg{border-radius:10px;padding:8px 10px;font-size:13px;margin:4px 0 8px}.aimsg.ok{background:var(--gl);color:var(--g2)}.aimsg.doubt{background:var(--al);color:#5a3d00}.aimsg.fail{background:var(--redl);color:var(--red)}.aimsg.skip{background:#EEF0EF;color:var(--mute)}
.tl{border-left:2px solid var(--line);margin-left:6px;padding-left:12px}
.tl .e{position:relative;padding-bottom:12px}.tl .e::before{content:"";position:absolute;left:-18px;top:5px;width:10px;height:10px;border-radius:5px;background:var(--g)}
.tl .e b{font-size:14px}.tl .e .note{font-size:12px}
.steps{display:flex;gap:4px;margin-bottom:12px}.steps span{flex:1;height:4px;border-radius:2px;background:var(--line)}.steps span.on{background:var(--g)}
.chk{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px}
.chk label{margin:0;display:flex;gap:8px;align-items:center;border:1.5px solid var(--line);border-radius:12px;padding:9px 10px;color:var(--ink);cursor:pointer;background:#fff;font-size:14px}
.chk label:has(input:checked){border-color:var(--g);background:var(--gl)}
.bar2{position:sticky;bottom:0;background:#fffffff2;border-top:1px solid var(--line);padding:10px 0 calc(10px + env(safe-area-inset-bottom));display:flex;gap:8px;align-items:center;justify-content:space-between;margin:0 -14px;padding-left:14px;padding-right:14px;z-index:4}
.prog{height:8px;border-radius:4px;background:var(--line);overflow:hidden;margin:6px 0}.prog i{display:block;height:100%;background:var(--g)}
.mini{font-size:12px;color:var(--mute)}
`;

function init(){
  if (META !== null) return;
  ({api, run, shell, ask, openSheet, closeSheet, toast, esc, fmt, go, download, qparam, ts, today, yen, $, me, accName} = window.YDD);
  const st = document.createElement("style"); st.textContent = CSS; document.head.appendChild(st);
  META = false;
}
async function meta(force){ if (!META || force) META = await api("/api/asset/meta"); return META; }
const stName = c => ((META && META.stores.find(s => s.code === c)) || {}).name || accName(c) || c;
const badge = (k, txt) => `<span class="ast ${esc(k)}">${esc(txt)}</span>`;
const aBadge = a => badge(a.status, a.status_text || (META && META.status[a.status]) || a.status) + (a.cond && a.cond !== "正常" && a.status === "active" ? " " + badge("doubt", a.cond) : "");
const VTXT = {ok:"AI 符合", doubt:"AI 存疑", fail:"AI 不符合", skip:"未检测"};
const mStatus = m => badge(m.status, m.kind === "stockin" && m.status === "shipped" ? "待入库" : m.status_text);
const sel = (id, opts, v, first) => `<select id="${id}">${first ? `<option value="">${esc(first)}</option>` : ""}${opts.map(o => `<option value="${esc(o[0])}" ${String(o[0]) === String(v ?? "") ? "selected" : ""}>${esc(o[1])}</option>`).join("")}</select>`;
const storeOpts = (ex) => META.stores.filter(s => s.code !== ex).map(s => [s.code, s.name + "（" + s.code + "）"]);
const itemOpts = () => META.items.filter(i => i.active).map(i => [i.id, i.name]);
const qs = o => Object.entries(o).filter(([k, v]) => v !== "" && v != null).map(([k, v]) => k + "=" + encodeURIComponent(v)).join("&");
const aiMsg = ai => !ai ? "" : `<div class="aimsg ${esc(ai.verdict)}"><b>${VTXT[ai.verdict] || ""}</b>${ai.reason ? "：" + esc(ai.reason) : ""}${ai.label_text ? `　标签：${esc(ai.label_text)}` : ""}</div>`;

// ---------------------------------------------------------------- 照片：压缩 + 上传 + AI
function compress(file, max = 1600, q = 0.82){
  return new Promise((res, rej) => {
    const url = URL.createObjectURL(file), img = new Image();
    img.onload = () => {
      const k = Math.min(1, max / Math.max(img.width, img.height));
      const cv = document.createElement("canvas"); cv.width = Math.round(img.width * k); cv.height = Math.round(img.height * k);
      cv.getContext("2d").drawImage(img, 0, 0, cv.width, cv.height); URL.revokeObjectURL(url);
      res(cv.toDataURL("image/jpeg", q));
    };
    img.onerror = () => { URL.revokeObjectURL(url); rej(new Error("无法读取这张照片，请重新拍摄")); };
    img.src = url;
  });
}
// 照片栏：opts {ctx, assetNo, itemName, check, max, store, onChange}
function photoBox(el, opts = {}){
  const list = [];
  const max = opts.max || 3;
  const draw = () => {
    el.innerHTML = `<div class="phs">${list.map((p, i) => `<div class="p"><img src="${esc(p.thumb || p.url)}">${p.ai && opts.check ? `<div class="v ${esc(p.ai.verdict)}">${VTXT[p.ai.verdict] || ""}</div>` : ""}<button class="x" data-i="${i}">✕</button></div>`).join("")}
      ${list.length < max ? `<button class="add" type="button"><i>📷</i>${list.length ? "再拍一张" : "拍照"}</button>` : ""}</div>
      <div class="aiwrap">${opts.check && list.length ? aiMsg(list[list.length - 1].ai) : ""}</div>
      <input type="file" accept="image/*" capture="environment" class="hide">`;
    const inp = el.querySelector("input");
    const add = el.querySelector(".add");
    if (add) add.onclick = () => inp.click();
    inp.onchange = () => { const f = inp.files[0]; if (!f) return;
      run(add, async () => {
        const data = await compress(f);
        const r = await api("/api/asset/photo", {method:"POST", body:{data, ctx:opts.ctx || "photo", assetNo:opts.assetNo || "", itemName:opts.itemName || "", check:!!opts.check, store:opts.store || ""}});
        list.push(r); draw(); opts.onChange && opts.onChange(list);
        if (opts.check && r.ai && r.ai.verdict === "fail") toast(r.ai.reason || "AI 判定不符合，请重新拍摄");
      });
    };
    el.querySelectorAll("[data-i]").forEach(b => b.onclick = () => { list.splice(+b.dataset.i, 1); draw(); opts.onChange && opts.onChange(list); });
  };
  draw();
  return { keys: () => list.map(p => p.key), list: () => list, best: () => { const o = {ok:3, skip:2, doubt:1, fail:0}; return list.reduce((a, p) => !a || (o[p.ai && p.ai.verdict] ?? 2) > (o[a.ai && a.ai.verdict] ?? 2) ? p : a, null); } };
}
const thumbs = ps => ps && ps.length ? `<div class="phs">${ps.map(p => `<a class="p" href="${esc(p.url)}" target="_blank"><img src="${esc(p.thumb)}" loading="lazy"></a>`).join("")}</div>` : "";

// ---------------------------------------------------------------- 资产履历（共用）
async function detailSheet(id, after){
  const d = await api("/api/asset/detail?id=" + id), a = d.asset, role = me().role;
  const sh = openSheet(`<h3>${esc(a.name)} <span class="note">${esc(a.asset_no)}</span></h3>
    <div class="card" style="padding:12px">
      <div class="mr"><span class="note">状态</span><span>${aBadge(a)}</span></div>
      <div class="mr"><span class="note">归属门店</span><b>${esc(a.store_name)}</b></div>
      <div class="mr"><span class="note">购入时间</span><span>${esc(a.buy_date || "—")}</span></div>
      <div class="mr"><span class="note">价格</span><span>${yen(a.price)}</span></div>
      ${a.note ? `<div class="mr"><span class="note">备注</span><span>${esc(a.note)}</span></div>` : ""}
    </div>
    <h3 style="font-size:15px">履历</h3>
    <div class="tl">${d.events.map(e => `<div class="e"><b>${esc(e.kind_text)}</b> <span class="note">${ts(e.t)} · ${esc(e.who_name)}</span>${e.detail ? `<div class="note">${esc(e.detail)}</div>` : ""}${thumbs(e.photos)}</div>`).join("") || `<div class="note">暂无</div>`}</div>
    <div class="g2" style="margin-top:8px"><button class="btn sec" id="dx">关闭</button>${role === "asset" ? `<button class="btn" id="de">修改资料</button>` : ""}</div>`);
  sh.querySelector("#dx").onclick = closeSheet;
  const de = sh.querySelector("#de"); if (de) de.onclick = () => assetEditSheet(a, after);
}

// ================================================================ 门店
async function storeHome(){
  const m = shell("资产管理", me().name, false, `<div id="hb"></div><div id="hk"></div>
    <div class="links">
      <a href="#a-list"><span class="ic">▣</span><span class="t">本店资产<small>清单与履历（编号对应设备上的标签）</small></span></a>
      <a href="#a-apply?k=transfer"><span class="ic">⇄</span><span class="t">申请调拨<small>调出本店资产、或申请别店资产调入</small></span></a>
      <a href="#a-apply?k=scrap"><span class="ic">✕</span><span class="t">申请报废<small>拍照说明，资产管理员审批</small></span></a>
    </div><div id="hm"></div>`);
  await run(null, async () => {
    await meta();
    const d = await api("/api/asset/store/home");
    if (location.hash !== "#a") return;
    let b = "";
    d.tasks.forEach(t => {
      const left = t.progress.n - t.progress.done;
      b += `<button class="banner ${t.overdue ? "err" : "info"}" data-go="#a-count?id=${t.id}"><span><b style="font-size:15px">${esc(t.name)}</b><br>${t.submitted && !t.recount ? "已提交，等待复核" : t.recount ? `有 ${t.recount} 件被退回重盘` : `还有 ${left} 件未盘 · 截止 ${esc(t.end_date)}`}</span><span>去盘点 ›</span></button>`;
    });
    d.todo.forEach(x => {
      const ship = x.kind === "transfer" && x.status === "approved";
      b += `<button class="banner ${x.overdue ? "err" : "ok"}" data-mv="${x.id}"><span>${ship ? `调拨出库：<b style="font-size:15px">${esc(x.name)}</b> 送往 ${esc(x.to_name)}` : x.kind === "stockin" ? `待入库：<b style="font-size:15px">${esc(x.name)}</b> ${esc(x.asset_no)}${x.expect_date ? `<br><span class="mini">预计 ${esc(x.expect_date)} 到货</span>` : ""}` : `待收货：<b style="font-size:15px">${esc(x.name)}</b> 来自 ${esc(x.from_name)}`}</span><span>${ship ? "去出库" : x.kind === "stockin" ? "去入库" : "去收货"} ›</span></button>`;
    });
    $("hb").innerHTML = b;
    $("hb").querySelectorAll("[data-go]").forEach(x => x.onclick = () => go(x.dataset.go));
    $("hb").querySelectorAll("[data-mv]").forEach(x => x.onclick = () => { const mv = d.todo.find(y => y.id === +x.dataset.mv);
      (mv.status === "approved" ? shipSheet : receiveSheet)(mv, () => storeHome()); });
    $("hk").innerHTML = `<div class="kpis"><div class="kpi"><div>本店在用资产</div><b>${d.count}</b> <span class="note">件</span></div><div class="kpi"><div>资产原值</div><b style="font-size:19px">${yen(d.value)}</b></div></div>`;
    $("hm").innerHTML = d.mine.length ? `<div class="card"><h2>我的申请</h2>${d.mine.map(x => `<div class="al" style="cursor:default"><span class="t"><b>${esc(x.kind_text)} · ${esc(x.name)}</b><small>${esc(x.asset_no)}${x.kind === "transfer" ? ` · ${esc(x.from_name)} → ${esc(x.to_name)}` : ""}${x.decide_note ? " · " + esc(x.decide_note) : ""}</small></span>${mStatus(x)}${x.status === "pending" ? `<button class="btn link sm" data-cx="${x.id}">撤回</button>` : ""}</div>`).join("")}</div>` : "";
    $("hm").querySelectorAll("[data-cx]").forEach(x => x.onclick = async () => { if (!(await ask({text:"撤回这笔申请？", ok:"撤回", danger:true})).ok) return;
      run(null, async () => { await api(`/api/asset/move/${x.dataset.cx}/cancel`, {method:"POST", body:{}}); toast("已撤回"); storeHome(); }); });
  });
}

function shipSheet(mv, after){
  const sh = openSheet(`<h3>调拨出库</h3><p class="note" style="margin-top:0">${esc(mv.name)} ${esc(mv.asset_no)} · 送往 <b>${esc(mv.to_name)}</b></p>
    <div class="f"><label>出库照片（拍设备与标签，至少 1 张）</label><div id="ph"></div></div>
    <div class="g2"><button class="btn sec" id="x">取消</button><button class="btn" id="ok">确认出库</button></div>`);
  const pb = photoBox(sh.querySelector("#ph"), {ctx:"ship", assetNo:mv.asset_no});
  sh.querySelector("#x").onclick = closeSheet;
  sh.querySelector("#ok").onclick = e => { if (!pb.keys().length) return toast("请先拍照");
    run(e.currentTarget, async () => { await api(`/api/asset/move/${mv.id}/ship`, {method:"POST", body:{photos:pb.keys()}}); closeSheet(); toast("已出库，等待对方收货"); after && after(); }); };
}

function receiveSheet(mv, after){
  const stock = mv.kind === "stockin";
  const conds = stock ? ["完好", "有损伤", "数量或型号不符"] : ["完好", "有损伤", "与申请不符"];
  let cond = "完好";
  const sh = openSheet(`<h3>${stock ? "购入入库" : "调拨收货"}</h3>
    <div class="card" style="padding:12px"><b>${esc(mv.name)}</b> <span class="note">${esc(mv.asset_no)}</span>
      <div class="note">${stock ? `财务购入 · ${yen(mv.price)}${mv.expect_date ? " · 预计 " + esc(mv.expect_date) + " 到货" : ""}` : `来自 ${esc(mv.from_name)} · ${esc(mv.reason || "")}`}</div>
      ${stock ? `<div class="aimsg doubt" style="margin-top:8px">请先把资产标签贴在设备上，再拍照（照片要看得到标签）</div>` : thumbs(mv.ship_photos)}</div>
    <div class="f"><label>到货照片（${stock ? "设备 + 标签" : "拍设备与标签"}）</label><div id="ph"></div></div>
    <div class="f"><label>到货状况</label><div class="chips" id="cd">${conds.map(c => `<button type="button" data-c="${c}" class="${c === cond ? "on" : ""}">${c}</button>`).join("")}</div></div>
    <div class="f"><label>说明（状况不是「完好」时必填）</label><textarea id="nt" placeholder="例：外壳有凹痕"></textarea></div>
    <div class="g2"><button class="btn redo" id="rf">拒收</button><button class="btn" id="ok">确认${stock ? "入库" : "收货"}</button></div>
    <button class="btn link block" id="x">稍后处理</button>`);
  const pb = photoBox(sh.querySelector("#ph"), {ctx: stock ? "stockin" : "recv", assetNo:mv.asset_no, itemName:mv.name, check:true});
  sh.querySelectorAll("#cd button").forEach(b => b.onclick = () => { cond = b.dataset.c; sh.querySelectorAll("#cd button").forEach(x => x.classList.toggle("on", x === b)); });
  sh.querySelector("#x").onclick = closeSheet;
  sh.querySelector("#ok").onclick = async e => {
    if (!pb.keys().length) return toast("请先拍照");
    const best = pb.best();
    if (best && best.ai && best.ai.verdict === "fail" && !(await ask({title:"AI 判定不符合", text:(best.ai.reason || "") + "。仍要确认吗？资产管理员会看到这个结果。", ok:"仍要确认"})).ok) return;
    const btn = sh.querySelector("#ok");
    run(btn, async () => { await api(`/api/asset/move/${mv.id}/receive`, {method:"POST", body:{photos:pb.keys(), cond, note:sh.querySelector("#nt").value.trim()}});
      closeSheet(); toast(stock ? "已入库" : "已收货"); after && after(); });
  };
  sh.querySelector("#rf").onclick = e => { const nt = sh.querySelector("#nt").value.trim(); if (!nt) { sh.querySelector("#nt").focus(); return toast("请在说明写拒收原因"); }
    run(e.currentTarget, async () => { await api(`/api/asset/move/${mv.id}/receive`, {method:"POST", body:{refuse:true, photos:pb.keys(), note:nt}}); closeSheet(); toast("已拒收，资产管理员会处理"); after && after(); }); };
}

async function storeList(){
  const m = shell("本店资产", me().name, true, `<div class="card"><input id="q" placeholder="搜索名称或编号"><div class="chips" style="margin:10px 0 0" id="it"></div></div><div class="card" id="ls"><div class="empty">载入中…</div></div>`);
  let all = [], item = "";
  const draw = () => {
    const q = $("q").value.trim().toUpperCase();
    const rs = all.filter(a => (!item || a.name === item) && (!q || a.asset_no.includes(q) || a.name.includes(q)));
    $("ls").innerHTML = `<h2>共 ${rs.length} 件</h2>` + (rs.map(a => `<div class="al" data-id="${a.id}"><span class="t"><b>${esc(a.name)}</b><small>${esc(a.asset_no)} · ${esc(a.buy_date || "")}</small></span>${aBadge(a)}</div>`).join("") || `<div class="empty">没有资料</div>`);
    $("ls").querySelectorAll("[data-id]").forEach(x => x.onclick = () => run(null, () => detailSheet(+x.dataset.id)));
  };
  await run(null, async () => {
    await meta(); all = (await api("/api/asset/assets")).assets;
    const names = [...new Set(all.map(a => a.name))];
    $("it").innerHTML = `<button class="on" data-n="">全部</button>` + names.map(n => `<button data-n="${esc(n)}">${esc(n)} ${all.filter(a => a.name === n).length}</button>`).join("");
    $("it").querySelectorAll("button").forEach(b => b.onclick = () => { item = b.dataset.n; $("it").querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b)); draw(); });
    $("q").oninput = draw; draw();
  });
}

async function storeApply(){
  const k = qparam("k") === "scrap" ? "scrap" : "transfer";
  const m = shell(k === "scrap" ? "申请报废" : "申请调拨", me().name, true, `<div id="bd"><div class="empty">载入中…</div></div>`);
  await run(null, async () => {
    await meta();
    let dir = "out", other = "", picked = new Set(), list = [];
    const SCRAP_R = ["损坏无法维修", "维修成本过高", "老旧淘汰", "其他"];
    $("bd").innerHTML = `${k === "transfer" ? `<div class="card"><div class="seg" id="dir"><button class="on" data-d="out"><b>调出</b><span>本店资产送到别店</span></button><button data-d="in"><b>调入</b><span>申请别店资产调来本店</span></button></div>
      <div class="f" style="margin-top:12px"><label id="ol">调入门店</label>${sel("os", storeOpts(me().code), "", "请选择门店")}</div></div>` : ""}
      <div class="card"><h2>选择资产 <span class="note" id="pc"></span></h2><input id="q" placeholder="搜索名称或编号" style="margin-bottom:6px"><div id="ls"></div></div>
      <div class="card">
        <div class="f"><label>${k === "scrap" ? "报废原因" : "调拨原因"}</label>${k === "scrap" ? `<div class="chips" id="rs">${SCRAP_R.map(r => `<button type="button" data-r="${r}">${r}</button>`).join("")}</div>` : `<input id="rsn" placeholder="例：旺季产能不足、门店装修暂存">`}</div>
        ${k === "transfer" ? `<div class="f"><label>希望完成日期（选填）</label><input type="date" id="dt"></div>` : `<div class="f"><label>照片（损坏处、整体，至少 1 张）</label><div id="ph"></div></div>`}
        <div class="f"><label>补充说明（选填）</label><textarea id="nt"></textarea></div>
        <button class="btn block" id="go">送出申请</button><p class="note" style="text-align:center;margin:8px 0 0">资产管理员审批后${k === "scrap" ? "即完成报废" : "，调出店出库、调入店收货"}</p></div>`;
    let reason = "";
    const pb = k === "scrap" ? photoBox($("ph"), {ctx:"scrap"}) : null;
    if (k === "scrap") $("rs").querySelectorAll("button").forEach(b => b.onclick = () => { reason = b.dataset.r; $("rs").querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b)); });
    const load = async () => {
      picked.clear();
      if (k === "transfer" && dir === "in" && !other) { list = []; return draw(); }
      list = (await api("/api/asset/assets?" + qs({store: k === "transfer" && dir === "in" ? other : "", status:"active"}))).assets.filter(a => !a.busy);
      draw();
    };
    const draw = () => {
      const q = ($("q").value || "").trim().toUpperCase();
      const rs = list.filter(a => !q || a.asset_no.includes(q) || a.name.includes(q));
      $("ls").innerHTML = rs.map(a => `<label class="al"><input type="checkbox" class="ck" data-id="${a.id}" ${picked.has(a.id) ? "checked" : ""}><span class="t"><b>${esc(a.name)}</b><small>${esc(a.asset_no)} · ${esc(a.buy_date || "")}${a.locked ? " · 盘点中" : ""}</small></span>${a.cond !== "正常" ? badge("doubt", a.cond) : ""}</label>`).join("")
        || `<div class="empty">${k === "transfer" && dir === "in" && !other ? "先选择要从哪家门店调入" : "没有可选的资产"}</div>`;
      $("ls").querySelectorAll("[data-id]").forEach(x => x.onchange = () => { x.checked ? picked.add(+x.dataset.id) : picked.delete(+x.dataset.id); $("pc").textContent = picked.size ? `已选 ${picked.size} 件` : ""; });
      $("pc").textContent = picked.size ? `已选 ${picked.size} 件` : "";
    };
    $("q").oninput = draw;
    if (k === "transfer") {
      $("dir").querySelectorAll("button").forEach(b => b.onclick = () => { dir = b.dataset.d; $("dir").querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b)); $("ol").textContent = dir === "out" ? "调入门店" : "从哪家门店调入"; run(null, load); });
      $("os").onchange = () => { other = $("os").value; if (dir === "in") run(null, load); };
    }
    $("go").onclick = e => {
      if (!picked.size) return toast("请选择资产");
      const body = {kind:k, ids:[...picked], note:$("nt").value.trim()};
      if (k === "transfer") { if (!other) return toast("请选择门店"); body.dir = dir; body.store = other; body.reason = $("rsn").value.trim(); body.date = $("dt").value; if (!body.reason) return toast("请填写调拨原因"); }
      else { if (!reason) return toast("请选择报废原因"); if (!pb.keys().length) return toast("请拍照"); body.reason = reason; body.photos = pb.keys(); }
      run(e.currentTarget, async () => { await api("/api/asset/request", {method:"POST", body}); toast("已送出，等待资产管理员审批"); go("#a"); });
    };
    await load();
  });
}

async function storeCount(){
  const id = +qparam("id");
  const m = shell("资产盘点", me().name, true, `<div id="bd"><div class="empty">载入中…</div></div>`);
  const load = async () => {
    await meta();
    const d = await api("/api/asset/count/detail?id=" + id);
    if (!location.hash.startsWith("#a-count")) return;
    const t = d.task, p = d.progress, open = t.status === "open", sub = !!d.submitted;
    const lines = d.lines.filter(l => l.status !== "extra"), extras = d.lines.filter(l => l.status === "extra");
    const recount = lines.filter(l => l.review === "recount" && l.status === "todo");
    const canEdit = l => open && (!sub || l.review === "recount");
    $("bd").innerHTML = `<div class="card"><h2>${esc(t.name)} ${badge(open ? (t.overdue ? "fail" : "pending") : "done", open ? (t.overdue ? "已逾期" : "进行中") : t.status_text)}</h2>
        <div class="note">${esc(t.start_date)} ～ ${esc(t.end_date)}${t.rules.note ? " · " + esc(t.rules.note) : ""}</div>
        <div class="prog"><i style="width:${p.n ? 100 * p.done / p.n : 0}%"></i></div>
        <div class="row sb note"><span>已盘 ${p.done} / ${p.n}</span><span>符合 ${p.ok} · 存疑 ${p.doubt} · 找不到 ${p.missing} · 盘盈 ${p.extra}</span></div>
        ${t.rules.photo !== "none" ? `<div class="aimsg skip" style="margin-top:8px">每件拍一张照片，<b>照片要看得到设备和资产标签</b>${t.rules.ai ? "，系统会用 AI 核对" : ""}</div>` : ""}</div>
      ${recount.length ? `<div class="banner err" style="cursor:default">资产管理员退回 ${recount.length} 件，请重新盘点</div>` : ""}
      <div class="card"><h2>盘点清单</h2>${lines.map(l => `<div class="al" data-l="${l.id}">${l.photos[0] ? `<img class="th" src="${esc(l.photos[0].thumb)}">` : `<span class="th"></span>`}<span class="t"><b>${esc(l.name)}</b><small>${esc(l.asset_no)}${l.review === "recount" ? " · 退回：" + esc(l.review_note) : l.note ? " · " + esc(l.note) : ""}</small></span>${badge(l.status, l.status_text)}</div>`).join("")}</div>
      <div class="card"><h2>盘盈（清单上没有、店里有的资产）${open && !sub ? `<button class="btn sm sec" id="ex">＋ 登记</button>` : ""}</h2>
        ${extras.map(l => `<div class="al" style="cursor:default">${l.photos[0] ? `<img class="th" src="${esc(l.photos[0].thumb)}">` : ""}<span class="t"><b>${esc(l.name)}</b><small>${esc(l.asset_no || "无标签")}${l.note ? " · " + esc(l.note) : ""}</small></span>${open && !sub ? `<button class="btn link sm" data-dx="${l.id}">删除</button>` : badge("extra", l.review_text || "盘盈")}</div>`).join("") || `<div class="note">没有</div>`}</div>
      ${open ? `<div class="bar2"><span class="note">${sub && !recount.length ? "已提交 " + ts(d.submitted) : `还有 ${p.n - p.done} 件未盘`}</span><button class="btn" id="sb" ${(sub && !recount.length) || p.n - p.done ? "disabled" : ""}>${sub && !recount.length ? "已提交" : "提交盘点结果"}</button></div>` : ""}`;
    $("bd").querySelectorAll("[data-l]").forEach(x => x.onclick = () => { const l = lines.find(y => y.id === +x.dataset.l);
      if (!canEdit(l)) return run(null, () => detailSheet(l.asset_id));
      lineSheet(t, l, load); });
    const ex = $("ex"); if (ex) ex.onclick = () => extraSheet(t, load);
    $("bd").querySelectorAll("[data-dx]").forEach(x => x.onclick = () => run(null, async () => { await api("/api/asset/count/extra/delete", {method:"POST", body:{id:+x.dataset.dx}}); load(); }));
    const sb = $("sb"); if (sb) sb.onclick = async e => { if (!(await ask({title:"提交盘点结果", text:"提交后不能再修改，确定提交？", ok:"提交"})).ok) return;
      run(sb, async () => { await api("/api/asset/count/submit", {method:"POST", body:{task:id}}); toast("已提交，等待资产管理员复核"); load(); }); };
  };
  run(null, load);
}

function lineSheet(t, l, after){
  let cond = l.cond || l.asset_cond || "正常";
  const needPhoto = t.rules.photo !== "none";
  const sh = openSheet(`<h3>${esc(l.name)}</h3><p class="note" style="margin-top:0">标签编号：<b style="color:var(--ink);font-size:16px">${esc(l.asset_no)}</b></p>
    ${l.review === "recount" ? `<div class="aimsg fail">退回原因：${esc(l.review_note)}</div>` : ""}
    ${needPhoto ? `<div class="f"><label>拍照（设备 + 标签）</label><div id="ph"></div></div>` : ""}
    <div class="f"><label>状况</label><div class="chips" id="cd">${META.conds.map(c => `<button type="button" data-c="${c}" class="${c === cond ? "on" : ""}">${c}</button>`).join("")}</div></div>
    <div class="f"><label>说明（选填）</label><input id="nt" value="${esc(l.status !== "missing" ? l.note || "" : "")}"></div>
    <button class="btn block" id="ok">确认找到</button>
    <div class="g2" style="margin-top:8px"><button class="btn sec" id="x">取消</button><button class="btn redo" id="ms">找不到</button></div>`);
  const pb = needPhoto ? photoBox(sh.querySelector("#ph"), {ctx:"count", assetNo:l.asset_no, itemName:l.name, check:t.rules.ai, max:1}) : null;
  sh.querySelectorAll("#cd button").forEach(b => b.onclick = () => { cond = b.dataset.c; sh.querySelectorAll("#cd button").forEach(x => x.classList.toggle("on", x === b)); });
  sh.querySelector("#x").onclick = closeSheet;
  sh.querySelector("#ok").onclick = async () => {
    if (pb && !pb.keys().length) return toast("请先拍照");
    const best = pb && pb.best();
    if (best && best.ai && best.ai.verdict === "fail" && !(await ask({title:"AI 判定不符合", text:(best.ai.reason || "") + "。建议重新拍摄；仍要送出吗？", ok:"仍要送出"})).ok) return;
    run(sh.querySelector("#ok"), async () => { await api("/api/asset/count/line", {method:"POST", body:{id:l.id, photos:pb ? pb.keys() : [], cond, note:sh.querySelector("#nt").value.trim()}}); closeSheet(); after(); });
  };
  sh.querySelector("#ms").onclick = async () => { const r = await ask({title:"找不到这件资产", text:l.name + " " + l.asset_no, input:true, placeholder:"说明原因，例：可能在仓库、已送修", ok:"确认找不到", danger:true});
    if (!r.ok) return; run(null, async () => { await api("/api/asset/count/line", {method:"POST", body:{id:l.id, missing:true, note:r.value}}); after(); }); };
}

function extraSheet(t, after){
  const sh = openSheet(`<h3>登记盘盈</h3><p class="note" style="margin-top:0">店里有、但清单上没有的资产</p>
    <div class="f"><label>资产名称</label>${sel("nm", META.items.filter(i => i.active).map(i => [i.name, i.name]), "", "请选择")}</div>
    <div class="f"><label>标签编号（没有标签就留空）</label><input id="no" autocapitalize="characters"></div>
    <div class="f"><label>照片</label><div id="ph"></div></div>
    <div class="f"><label>说明</label><input id="nt" placeholder="例：其他门店调来未登记"></div>
    <div class="g2"><button class="btn sec" id="x">取消</button><button class="btn" id="ok">登记</button></div>`);
  const pb = photoBox(sh.querySelector("#ph"), {ctx:"count", check:t.rules.ai, max:1});
  sh.querySelector("#x").onclick = closeSheet;
  sh.querySelector("#ok").onclick = e => { const nm = sh.querySelector("#nm").value; if (!nm) return toast("请选择资产名称"); if (!pb.keys().length) return toast("请拍照");
    run(e.currentTarget, async () => { await api("/api/asset/count/extra", {method:"POST", body:{task:t.id, name:nm, no:sh.querySelector("#no").value.trim(), photos:pb.keys(), note:sh.querySelector("#nt").value.trim()}}); closeSheet(); after(); }); };
}

// ================================================================ 资产管理员
async function adminHome(){
  shell("资产管理", me().name + " · 资产管理员", false, `<div id="hb"></div><div id="hk"></div>
    <div class="links">
      <a href="#approvals"><span class="ic">✓</span><span class="t">调拨 / 报废审批<small>审批门店申请、查看所有调拨报废入库记录</small></span></a>
      <a href="#counts"><span class="ic">◎</span><span class="t">资产盘点<small>发起盘点、进度、复核与结案</small></span></a>
      <a href="#assets"><span class="ic">▣</span><span class="t">资产总表<small>查询、维护、直接调拨 / 报废、导出、印标签</small></span></a>
      <a href="#import"><span class="ic">⇪</span><span class="t">现存资产导入<small>一份 Excel 建好所有门店资产</small></span></a>
      <a href="#catalog"><span class="ic">≡</span><span class="t">资产目录<small>品项名称、代码、固定价格</small></span></a>
      <a href="#asettings"><span class="ic">⚙</span><span class="t">设定<small>编号规则、照片储存（OSS）、AI 检测</small></span></a>
    </div>`);
  run(null, async () => {
    const d = await api("/api/asset/admin/home");
    if (location.hash.replace("#", "") !== "") return;
    let b = "";
    if (d.pending.length) b += `<button class="banner info" data-go="#approvals"><span>有 <b>${d.pending.length}</b> 笔调拨 / 报废等待审批</span><span>去审批 ›</span></button>`;
    d.tasks.forEach(t => b += `<button class="banner ${t.overdue ? "err" : "ok"}" data-go="#count?id=${t.id}"><span><b style="font-size:15px">${esc(t.name)}</b><br>已盘 ${t.progress.done}/${t.progress.n}${t.overdue ? " · 已过截止日" : " · 截止 " + esc(t.end_date)}</span><span>查看 ›</span></button>`);
    if (d.overdue.length) b += `<button class="banner err" data-go="#approvals?f=stockin"><span>${d.overdue.length} 件购入资产逾期未入库</span><span>查看 ›</span></button>`;
    if (d.refused.length) b += `<button class="banner err" data-go="#approvals?f=refused"><span>${d.refused.length} 件购入资产被门店拒收，待处理</span><span>查看 ›</span></button>`;
    if (d.unprinted) b += `<button class="banner info" data-go="#assets?unprinted=1"><span>${d.unprinted} 件资产标签尚未打印</span><span>去打印 ›</span></button>`;
    $("hb").innerHTML = b;
    $("hb").querySelectorAll("[data-go]").forEach(x => x.onclick = () => go(x.dataset.go));
    $("hk").innerHTML = `<div class="kpis"><div class="kpi"><div>在用资产</div><b>${d.count}</b> <span class="note">件 · ${d.stores} 店</span></div><div class="kpi"><div>资产原值</div><b style="font-size:19px">${yen(d.value)}</b></div>
      <div class="kpi"><div>本月调拨</div><b>${d.monthTransfer}</b> <span class="note">笔</span></div><div class="kpi"><div>本月报废 / 待入库</div><b>${d.monthScrap}</b> <span class="note">/ ${d.pendingStockin}</span></div></div>`;
  });
}

async function adminApprovals(){
  const f0 = qparam("f") || "pending";
  shell("调拨 / 报废审批", "资产管理员", true, `<div class="chips" id="fl">${[["pending","待审批"],["open","进行中"],["stockin","待入库"],["refused","拒收"],["all","全部记录"]].map(([k, t]) => `<button data-f="${k}" class="${k === f0 ? "on" : ""}">${t}</button>`).join("")}</div>
    <div id="ls"><div class="empty">载入中…</div></div><button class="btn sec block" id="ex">导出调拨 / 报废 / 入库记录</button>`);
  $("ex").onclick = () => download("/api/asset/export?kind=moves");
  let f = f0;
  const load = async () => {
    await meta();
    const q = {pending:{status:"pending"}, open:{status:"open"}, stockin:{kind:"stockin", status:"shipped"}, refused:{status:"refused"}, all:{}}[f];
    const d = await api("/api/asset/moves?" + qs(q));
    $("ls").innerHTML = d.moves.map(x => `<div class="rec"><div class="l1"><span>${esc(x.kind_text)} · ${esc(x.name)}</span>${mStatus(x)}</div>
      <div class="route">${esc(x.asset_no)} · ${yen(x.price)}</div>
      <div class="meta">${x.kind === "scrap" ? esc(x.from_name) : x.kind === "stockin" ? "入库门店：" + esc(x.to_name) + (x.expect_date ? " · 预计 " + esc(x.expect_date) : "") : `${esc(x.from_name)} → ${esc(x.to_name)}`}</div>
      ${x.reason ? `<div class="meta">原因：${esc(x.reason)}${x.note ? "；" + esc(x.note) : ""}</div>` : ""}
      <div class="meta">${esc(x.created_name)} · ${ts(x.created_at)}${x.overdue ? ` · <b style="color:var(--red)">逾期未入库</b>` : ""}</div>
      ${thumbs(x.photos)}${x.ship_photos.length ? `<div class="mini">出库照片</div>` + thumbs(x.ship_photos) : ""}${x.recv_photos.length ? `<div class="mini">收货 / 入库照片 · ${esc(x.recv_cond)}</div>` + thumbs(x.recv_photos) : ""}
      ${x.recv_note ? `<div class="ev ${x.status === "refused" ? "red" : ""}">${esc(x.recv_note)}</div>` : ""}${x.decide_note ? `<div class="ev">审批：${esc(x.decide_note)}</div>` : ""}
      <div class="acts">${x.status === "pending" ? `<button class="btn redo sm" data-rj="${x.id}">驳回</button><button class="btn sm" data-ok="${x.id}">同意</button>` : ""}
        ${x.status === "refused" && x.kind === "stockin" ? `<button class="btn sec sm" data-as="${x.asset_id}">处理资产</button>` : ""}<button class="btn link sm" data-d="${x.asset_id}">履历</button></div></div>`).join("") || `<div class="empty card">没有记录</div>`;
    $("ls").querySelectorAll("[data-ok]").forEach(b => b.onclick = () => run(b, async () => { await api(`/api/asset/move/${b.dataset.ok}/decide`, {method:"POST", body:{ok:true}}); toast("已同意"); load(); }));
    $("ls").querySelectorAll("[data-rj]").forEach(b => b.onclick = async () => { const r = await ask({title:"驳回申请", input:true, placeholder:"驳回原因（门店会看到）", ok:"驳回", danger:true}); if (!r.ok) return;
      run(null, async () => { await api(`/api/asset/move/${b.dataset.rj}/decide`, {method:"POST", body:{ok:false, note:r.value}}); toast("已驳回"); load(); }); });
    $("ls").querySelectorAll("[data-d]").forEach(b => b.onclick = () => run(null, () => detailSheet(+b.dataset.d, load)));
    $("ls").querySelectorAll("[data-as]").forEach(b => b.onclick = () => run(null, async () => { const a = (await api("/api/asset/detail?id=" + b.dataset.as)).asset; assetEditSheet(a, load); }));
  };
  $("fl").querySelectorAll("button").forEach(b => b.onclick = () => { f = b.dataset.f; $("fl").querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b)); run(null, load); });
  run(null, load);
}

function assetEditSheet(a, after){
  const isNew = !a;
  a = a || {item_id:"", store:"", buy_date:"", price:"", cond:"正常", note:"", asset_no:""};
  const sh = openSheet(`<h3>${isNew ? "新增资产" : "修改资产"}</h3>
    ${!isNew && a.status === "pending_in" ? `<div class="aimsg doubt">这件资产尚未入库${a.store_name ? "（" + esc(a.store_name) + "）" : ""}。若门店拒收，可在这里改门店后到「审批 › 拒收」请门店重新入库，或直接报废。</div>` : ""}
    <div class="f"><label>资产编号（新增时留空自动编号）</label><input id="no" value="${esc(a.asset_no)}" autocapitalize="characters"></div>
    <div class="g2 f"><div><label>品项</label>${sel("it", itemOpts(), a.item_id)}</div><div><label>归属门店</label>${sel("st", storeOpts(), a.store, "请选择")}</div></div>
    <div class="g2 f"><div><label>购入时间</label><input id="bd" value="${esc(a.buy_date)}" placeholder="2025-06 或 2025-06-12"></div><div><label>价格（空白 = 目录价）</label><input id="pr" inputmode="decimal" value="${esc(a.price ?? "")}"></div></div>
    <div class="g2 f"><div><label>状况</label>${sel("cd", META.conds.map(c => [c, c]), a.cond)}</div><div><label>备注</label><input id="nt" value="${esc(a.note || "")}"></div></div>
    <div class="g2"><button class="btn sec" id="x">取消</button><button class="btn" id="ok">保存</button></div>
    ${!isNew && a.status === "pending_in" ? `<div class="g2" style="margin-top:8px"><button class="btn sec" id="ri">请门店重新入库</button><button class="btn redo" id="sp">报废</button></div>` : ""}`);
  sh.querySelector("#x").onclick = closeSheet;
  sh.querySelector("#ok").onclick = e => run(e.currentTarget, async () => {
    await api("/api/asset/asset", {method:"POST", body:{id:isNew ? null : a.id, asset_no:sh.querySelector("#no").value.trim(), item_id:+sh.querySelector("#it").value, store:sh.querySelector("#st").value,
      buy_date:sh.querySelector("#bd").value.trim(), price:sh.querySelector("#pr").value.trim(), cond:sh.querySelector("#cd").value, note:sh.querySelector("#nt").value.trim()}});
    closeSheet(); toast("已保存"); after && after(); });
  const ri = sh.querySelector("#ri"); if (ri) ri.onclick = e => run(e.currentTarget, async () => { await api("/api/asset/restock", {method:"POST", body:{id:a.id, store:sh.querySelector("#st").value}}); closeSheet(); toast("已通知门店重新入库"); after && after(); });
  const sp = sh.querySelector("#sp"); if (sp) sp.onclick = async () => { const r = await ask({title:"报废这件资产", input:true, placeholder:"原因", ok:"报废", danger:true}); if (!r.ok) return;
    run(null, async () => { await api("/api/asset/restock", {method:"POST", body:{id:a.id, scrap:true, note:r.value}}); toast("已报废"); after && after(); }); };
}

async function adminAssets(){
  shell("资产总表", "资产管理员", true, `<div class="card"><div class="g2 f"><div>${sel("fs", [], "", "全部门店")}</div><div>${sel("fi", [], "", "全部品项")}</div></div>
      <div class="g2"><div>${sel("fst", [["live","在用 / 调拨中 / 待入库"],["active","在用"],["transit","调拨中"],["pending_in","待入库"],["scrapped","已报废"],["lost","盘亏"]], "live", "全部状态")}</div><input id="q" placeholder="搜索编号 / 名称"></div>
      <label style="display:flex;gap:8px;align-items:center;color:var(--ink);margin:10px 0 0"><input type="checkbox" id="up" ${qparam("unprinted") ? "checked" : ""}> 只看标签未打印</label></div>
    <div class="card"><h2><span id="cnt">载入中…</span><span class="row"><button class="btn sm sec" id="add">＋ 新增</button><button class="btn sm sec" id="ex">导出</button></span></h2>
      <label style="display:flex;gap:8px;align-items:center;color:var(--ink)"><input type="checkbox" id="all"> 全选</label><div id="ls"></div></div>
    <div class="bar2 hide" id="ab"><span id="sc" class="note"></span><span class="row"><button class="btn sm sec" id="lb">印标签</button><button class="btn sm sec" id="tr">调拨</button><button class="btn sm redo" id="sp">报废</button></span></div>`);
  await run(null, meta);
  $("fs").innerHTML = `<option value="">全部门店</option>` + storeOpts().map(o => `<option value="${esc(o[0])}">${esc(o[1])}</option>`).join("");
  $("fi").innerHTML = `<option value="">全部品项</option>` + META.items.map(i => `<option value="${i.id}">${esc(i.name)}</option>`).join("");
  let list = [], picked = new Set();
  const load = () => run(null, async () => {
    const d = await api("/api/asset/assets?" + qs({store:$("fs").value, item:$("fi").value, status:$("fst").value || "all", q:$("q").value.trim(), unprinted:$("up").checked ? 1 : ""}));
    list = d.assets; picked.clear(); $("all").checked = false;
    $("cnt").textContent = `${d.total} 件 · ${yen(d.value)}`;
    $("ls").innerHTML = list.map(a => `<div class="al"><input type="checkbox" class="ck" data-c="${a.id}"><span class="t" data-id="${a.id}"><b>${esc(a.name)} <span class="note" style="font-weight:400">${esc(a.asset_no)}</span></b><small>${esc(a.store_name)} · ${esc(a.buy_date || "")} · ${yen(a.price)}${a.label_printed ? "" : " · 标签未印"}${a.locked ? " · 盘点中" : ""}</small></span>${aBadge(a)}</div>`).join("") || `<div class="empty">没有资料</div>`;
    $("ls").querySelectorAll("[data-id]").forEach(x => x.onclick = () => run(null, () => detailSheet(+x.dataset.id, load)));
    $("ls").querySelectorAll("[data-c]").forEach(x => x.onchange = () => { x.checked ? picked.add(+x.dataset.c) : picked.delete(+x.dataset.c); bar(); });
    bar();
  });
  const bar = () => { $("ab").classList.toggle("hide", !picked.size); $("sc").textContent = `已选 ${picked.size} 件`; };
  ["fs", "fi", "fst", "up"].forEach(i => $(i).onchange = load);
  let qt; $("q").oninput = () => { clearTimeout(qt); qt = setTimeout(load, 350); };
  $("all").onchange = () => { $("ls").querySelectorAll("[data-c]").forEach(x => { x.checked = $("all").checked; x.checked ? picked.add(+x.dataset.c) : picked.delete(+x.dataset.c); }); bar(); };
  $("add").onclick = () => assetEditSheet(null, load);
  $("ex").onclick = () => download("/api/asset/export?kind=assets");
  $("lb").onclick = () => labelSheet({ids:[...picked]}, load);
  $("tr").onclick = () => { const sh = openSheet(`<h3>直接调拨 ${picked.size} 件</h3><p class="note" style="margin-top:0">不需审批，调出店出库、调入店收货即完成</p>
      <div class="f"><label>调入门店</label>${sel("dts", storeOpts(), "", "请选择")}</div><div class="f"><label>说明</label><input id="dtn"></div>
      <div class="g2"><button class="btn sec" id="x">取消</button><button class="btn" id="ok">建立调拨</button></div>`);
    sh.querySelector("#x").onclick = closeSheet;
    sh.querySelector("#ok").onclick = e => run(e.currentTarget, async () => { await api("/api/asset/direct", {method:"POST", body:{kind:"transfer", ids:[...picked], store:sh.querySelector("#dts").value, note:sh.querySelector("#dtn").value.trim()}}); closeSheet(); toast("已建立调拨，等待门店出库"); load(); }); };
  $("sp").onclick = async () => { const r = await ask({title:`直接报废 ${picked.size} 件`, input:true, placeholder:"报废原因", ok:"报废", danger:true}); if (!r.ok) return;
    run(null, async () => { await api("/api/asset/direct", {method:"POST", body:{kind:"scrap", ids:[...picked], note:r.value}}); toast("已报废"); load(); }); };
  load();
}

// ---------------------------------------------------------------- 标签
const qrSvg = (rows, px) => { const n = rows.length, q = 2, s = (n + q * 2);
  let p = ""; rows.forEach((r, y) => { for (let x = 0; x < n; x++) if (r[x] === "1") p += `M${x + q} ${y + q}h1v1h-1z`; });
  return `<svg viewBox="0 0 ${s} ${s}" width="${px}" height="${px}" shape-rendering="crispEdges"><rect width="${s}" height="${s}" fill="#fff"/><path d="${p}" fill="#000"/></svg>`; };
function labelSheet(body, after){
  const sh = openSheet(`<h3>印资产标签</h3>
    <div class="f"><label>标签纸</label><div class="seg" id="lt"><button class="on" data-t="therm"><b>标签机 50×30mm</b><span>每张一个标签</span></button><button data-t="a4"><b>A4 不干胶</b><span>每页 24 个（3×8）</span></button></div></div>
    <label style="display:flex;gap:8px;align-items:center;color:var(--ink);margin-bottom:12px"><input type="checkbox" id="mk" checked> 打印后标记为「已打印」</label>
    <div class="g2"><button class="btn sec" id="x">取消</button><button class="btn" id="ok">产生标签</button></div>`);
  let t = "therm";
  sh.querySelectorAll("#lt button").forEach(b => b.onclick = () => { t = b.dataset.t; sh.querySelectorAll("#lt button").forEach(x => x.classList.toggle("on", x === b)); });
  sh.querySelector("#x").onclick = closeSheet;
  sh.querySelector("#ok").onclick = e => {
    const w = window.open("", "_blank");
    run(e.currentTarget, async () => {
      const d = await api("/api/asset/labels", {method:"POST", body:Object.assign({}, body, {mark:sh.querySelector("#mk").checked})});
      if (!d.labels.length) { if (w) w.close(); return toast("没有可印的标签"); }
      const one = l => `<div class="lb"><div class="q">${qrSvg(l.qr, 200)}</div><div class="tx"><div class="b">1点点 资产</div><div class="no">${esc(l.no)}</div><div>${esc(l.name)}</div><div class="s">${esc(l.store)}${l.date ? " · " + esc(l.date) : ""}</div></div></div>`;
      const css = t === "therm"
        ? `@page{size:50mm 30mm;margin:0}body{margin:0}.lb{width:50mm;height:30mm;page-break-after:always;display:flex;align-items:center;gap:2mm;padding:1.5mm 2mm;box-sizing:border-box}.q svg{width:24mm;height:24mm}`
        : `@page{size:A4;margin:10mm 7mm}body{margin:0}.pg{display:grid;grid-template-columns:repeat(3,64mm);grid-auto-rows:34.6mm;gap:0 4mm}.lb{display:flex;align-items:center;gap:2mm;padding:2mm;box-sizing:border-box;border:.2mm dashed #ccc}.q svg{width:26mm;height:26mm}`;
      const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>资产标签</title><style>${css}*{font-family:"Microsoft YaHei","PingFang SC",sans-serif}.tx{font-size:8pt;line-height:1.25;min-width:0}.tx .b{font-weight:700;color:#007F61}.tx .no{font-weight:700;font-size:9pt;white-space:nowrap}.tx .s{font-size:7pt;color:#555}.tip{font:14px sans-serif;padding:10px;background:#FFF4DE}@media print{.tip{display:none}}</style></head><body><div class="tip">共 ${d.labels.length} 个标签。按 Ctrl+P（手机：分享 › 打印）列印；${t === "therm" ? "纸张选 50×30mm" : "纸张选 A4、缩放 100%"}。</div>${t === "therm" ? d.labels.map(one).join("") : `<div class="pg">${d.labels.map(one).join("")}</div>`}<script>setTimeout(()=>print(),400)<\/script></body></html>`;
      if (w) { w.document.write(html); w.document.close(); } else { const b = new Blob([html], {type:"text/html"}); location.href = URL.createObjectURL(b); }
      closeSheet(); after && after();
    });
  };
}

// ---------------------------------------------------------------- 目录
async function adminCatalog(){
  shell("资产目录", "资产管理员", true, `<div class="card" id="fc"><h2 id="ft">新增品项</h2>
    <div class="g2 f"><div><label>品项名称</label><input id="nm" placeholder="制冰机"></div><div><label>代码（编号用，英文）</label><input id="cd" placeholder="ZB" autocapitalize="characters"></div></div>
    <div class="g2 f"><div><label>固定价格（元）</label><input id="pr" inputmode="decimal"></div><label style="display:flex;gap:8px;align-items:center;color:var(--ink);margin-top:24px"><input type="checkbox" id="ac" checked> 启用</label></div>
    <div class="row end"><button class="btn link hide" id="cx">取消修改</button><button class="btn" id="sv">保存</button></div>
    <p class="note" style="margin:8px 0 0">编号规则：<b id="rule"></b></p></div>
    <div class="card"><h2>品项清单</h2><div class="scroll"><table class="tbl" id="tb"></table></div></div>`);
  let editing = null;
  const load = () => run(null, async () => {
    await meta(true);
    $("rule").textContent = `${META.prefix}-品项代码-年份-4位流水号，例：${META.prefix}-${($("cd").value || "ZB").toUpperCase()}-${today().slice(0,4)}-0001`;
    $("tb").innerHTML = `<thead><tr><th>品项</th><th>代码</th><th class="n">价格</th><th></th></tr></thead><tbody>${META.items.map(i => `<tr><td><b>${esc(i.name)}</b>${i.active ? "" : ' <span class="st off">停用</span>'}</td><td>${esc(i.code)}</td><td class="n">${yen(i.price)}</td><td><button class="btn link sm" data-e="${i.id}">修改</button></td></tr>`).join("")}</tbody>`;
    $("tb").querySelectorAll("[data-e]").forEach(b => b.onclick = () => { const i = META.items.find(x => x.id === +b.dataset.e); editing = i.id;
      $("nm").value = i.name; $("cd").value = i.code; $("pr").value = i.price; $("ac").checked = !!i.active; $("ft").textContent = "修改 " + i.name; $("cx").classList.remove("hide"); $("fc").scrollIntoView({behavior:"smooth"}); });
  });
  const reset = () => { editing = null; ["nm", "cd", "pr"].forEach(i => $(i).value = ""); $("ac").checked = true; $("ft").textContent = "新增品项"; $("cx").classList.add("hide"); };
  $("cx").onclick = reset;
  $("sv").onclick = e => run(e.currentTarget, async () => { await api("/api/asset/items", {method:"POST", body:{id:editing, name:$("nm").value.trim(), code:$("cd").value.trim(), price:$("pr").value.trim(), active:$("ac").checked}}); toast("已保存"); reset(); load(); });
  load();
}

// ---------------------------------------------------------------- 导入
async function adminImport(){
  shell("现存资产导入", "资产管理员", true, `<div class="card"><h2>1. 准备 Excel</h2>
      <p class="note" style="margin-top:0">一份表格包含所有门店。栏位：资产编号*、资产名称*、归属门店*（门店编号或名称）、购入时间*、价格、状态、备注。价格空白 = 用目录价。</p>
      <button class="btn sec sm" id="tp">下载导入模板</button></div>
    <div class="card"><h2>2. 上传档案</h2><input type="file" id="fl" accept=".xlsx,.csv,.txt"><p class="note">也可以从 Excel 复制贴上：</p><textarea id="tx" placeholder="含标题列一起贴上"></textarea>
      <label style="display:flex;gap:8px;align-items:center;color:var(--ink);margin:8px 0"><input type="checkbox" id="oa" checked> 资产名称不在目录时，自动新增品项</label>
      <label style="display:flex;gap:8px;align-items:center;color:var(--ink);margin:0 0 12px"><input type="checkbox" id="ou" checked> 编号已存在时，更新资料</label>
      <button class="btn block" id="pv">检查资料</button></div><div id="rs"></div>`);
  $("tp").onclick = () => download("/api/asset/template");
  let file = null;
  $("fl").onchange = () => { const f = $("fl").files[0]; if (!f) return; const r = new FileReader(); r.onload = () => { file = r.result; toast("已读取：" + f.name); }; r.readAsDataURL(f); };
  const body = apply => ({file:file || undefined, text:file ? undefined : $("tx").value, opts:{addItems:$("oa").checked, update:$("ou").checked}, apply});
  $("pv").onclick = e => { if (!file && !$("tx").value.trim()) return toast("请上传档案或贴上资料");
    run(e.currentTarget, async () => {
      const d = await api("/api/asset/import", {method:"POST", body:body(false)}), s = d.summary;
      $("rs").innerHTML = `<div class="card"><h2>3. 确认导入</h2><div class="kpis"><div class="kpi"><div>新增</div><b>${s.new}</b></div><div class="kpi"><div>更新</div><b>${s.update}</b></div><div class="kpi ${s.error ? "warn" : ""}"><div>错误（会略过）</div><b>${s.error}</b></div><div class="kpi"><div>新品项</div><b>${s.newItems}</b></div></div>
        ${d.newItems.length && s.newItems ? `<p class="note">将新增品项：${d.newItems.map(esc).join("、")}（代码自动编为 X1、X2…，可到资产目录修改）</p>` : ""}
        <div class="scroll"><table class="tbl"><thead><tr><th>行</th><th>结果</th><th>编号</th><th>名称</th><th>门店</th><th>购入</th><th>说明</th></tr></thead><tbody>${d.plan.filter(p => p.st === "error").concat(d.plan.filter(p => p.st !== "error").slice(0, 30)).map(p => `<tr><td>${p.line}</td><td>${badge(p.st === "error" ? "fail" : p.st === "new" ? "ok" : "pending", p.st === "error" ? "错误" : p.st === "new" ? "新增" : "更新")}</td><td>${esc(p.no)}</td><td>${esc(p.name)}</td><td>${esc(p.store ? stName(p.store) : p.raw_store)}</td><td>${esc(p.date || "")}</td><td class="wrap">${esc(p.msg || "")}</td></tr>`).join("")}</tbody></table></div>
        <button class="btn block" id="ap" style="margin-top:12px" ${s.new + s.update ? "" : "disabled"}>导入 ${s.new + s.update} 笔</button></div>`;
      $("ap").onclick = ev => run(ev.currentTarget, async () => {
        const r = await api("/api/asset/import", {method:"POST", body:body(true)});
        $("rs").innerHTML = `<div class="card"><h2>导入完成 ${badge("done", "批次 " + r.batch.slice(4, 12))}</h2>
          <table class="tbl"><thead><tr><th>门店</th><th class="n">件数</th><th class="n">原值</th></tr></thead><tbody>${r.stores.map(s => `<tr><td>${esc(s.name)}</td><td class="n">${s.n}</td><td class="n">${yen(s.value)}</td></tr>`).join("")}</tbody></table>
          ${r.errors.length ? `<p class="note">${r.errors.length} 笔错误已略过，修正后可再导入一次。</p>` : ""}
          <div class="g2" style="margin-top:10px"><button class="btn redo" id="ud">整批撤销（24 小时内）</button><button class="btn" id="lb">印这批标签</button></div></div>`;
        $("ud").onclick = async () => { if (!(await ask({text:"撤销这次导入的所有新增资产？", ok:"撤销", danger:true})).ok) return;
          run(null, async () => { const u = await api("/api/asset/import/undo", {method:"POST", body:{batch:r.batch}}); toast(`已撤销 ${u.n} 件`); $("rs").innerHTML = ""; }); };
        $("lb").onclick = () => labelSheet({}, null);
        file = null; $("fl").value = ""; $("tx").value = "";
      });
    }); };
}

// ---------------------------------------------------------------- 盘点（资产管理员）
async function adminCounts(){
  shell("资产盘点", "资产管理员", true, `<button class="btn hero" id="nw">＋ 发起盘点<span>选门店、品项、期限，门店手机拍照盘点</span></button><div style="height:12px"></div><div id="ls"><div class="empty">载入中…</div></div>`);
  $("nw").onclick = () => go("#count-new");
  run(null, async () => {
    const d = await api("/api/asset/counts");
    $("ls").innerHTML = d.tasks.map(t => `<div class="rec" data-id="${t.id}" style="cursor:pointer"><div class="l1"><span>${esc(t.name)}</span>${badge(t.status === "open" ? (t.overdue ? "fail" : "pending") : t.status === "closed" ? "done" : "cancelled", t.overdue ? "已逾期" : t.status_text)}</div>
      <div class="meta">${esc(t.ctype)} · ${t.mode === "sample" ? `抽盘 ${t.rules.pct}%` : "全盘"} · ${esc(t.start_date)} ～ ${esc(t.end_date)}</div>
      <div class="prog"><i style="width:${t.progress.n ? 100 * t.progress.done / t.progress.n : 0}%"></i></div>
      <div class="meta">已盘 ${t.progress.done}/${t.progress.n} · 找不到 ${t.progress.missing} · 盘盈 ${t.progress.extra}${t.status === "closed" && t.summary.lost != null ? ` · 盘亏 ${t.summary.lost} 件 ${yen(t.summary.lostValue)}` : ""}</div></div>`).join("") || `<div class="empty card">还没有盘点任务</div>`;
    $("ls").querySelectorAll("[data-id]").forEach(x => x.onclick = () => go("#count?id=" + x.dataset.id));
  });
}

async function adminCountNew(){
  shell("发起盘点", "资产管理员", true, `<div class="steps" id="sp"><span class="on"></span><span></span><span></span><span></span></div><div id="bd"></div>`);
  await run(null, meta);
  const nd = n => { const d = new Date(); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); };
  const ym = today().slice(0, 7).replace("-", " 年 ").replace(/^(\d+ 年 )0?/, "$1") + " 月";
  const T = {name:`${ym}资产盘点`, ctype:"月度盘点", stores:"all", items:"all", mode:"full", pct:20, photo:"each", ai:true, remind:true, lock:true, note:"", start_date:today(), end_date:nd(7), review_date:nd(10)};
  let step = 1;
  const draw = async () => {
    $("sp").querySelectorAll("span").forEach((s, i) => s.classList.toggle("on", i < step));
    const nav = (last) => `<div class="bar2"><button class="btn sec" id="pv">${step === 1 ? "取消" : "上一步"}</button><button class="btn" id="nx">${last ? "确认发起" : "下一步"}</button></div>`;
    if (step === 1) {
      $("bd").innerHTML = `<div class="card"><h2>1. 任务与范围</h2>
        <div class="f"><label>任务名称</label><input id="nm" value="${esc(T.name)}"></div>
        <div class="f"><label>类型</label><div class="chips" id="ct">${["月度盘点", "季度盘点", "年度盘点", "专项盘点"].map(c => `<button type="button" class="${c === T.ctype ? "on" : ""}">${c}</button>`).join("")}</div></div>
        <div class="f"><label>门店范围</label><div class="seg" id="sr"><button data-v="all" class="${T.stores === "all" ? "on" : ""}"><b>全部门店</b><span>${META.stores.length} 家</span></button><button data-v="pick" class="${T.stores !== "all" ? "on" : ""}"><b>指定门店</b><span>勾选要盘点的门店</span></button></div></div>
        <div id="sl" class="${T.stores === "all" ? "hide" : ""}"><div class="row" style="margin-bottom:6px"><button class="btn link sm" id="sa">全选</button><button class="btn link sm" id="sn">全不选</button></div><div class="chk">${META.stores.map(s => `<label><input type="checkbox" value="${esc(s.code)}" ${T.stores !== "all" && T.stores.includes(s.code) ? "checked" : ""}>${esc(s.name)}</label>`).join("")}</div></div></div>${nav()}`;
      $("ct").querySelectorAll("button").forEach(b => b.onclick = () => { T.ctype = b.textContent; $("ct").querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b)); });
      $("sr").querySelectorAll("button").forEach(b => b.onclick = () => { $("sr").querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b)); $("sl").classList.toggle("hide", b.dataset.v === "all"); T._pick = b.dataset.v === "pick"; });
      T._pick = T.stores !== "all";
      $("sa").onclick = () => $("sl").querySelectorAll("input").forEach(x => x.checked = true);
      $("sn").onclick = () => $("sl").querySelectorAll("input").forEach(x => x.checked = false);
      $("pv").onclick = () => history.back();
      $("nx").onclick = () => { T.name = $("nm").value.trim(); if (!T.name) return toast("请填写任务名称");
        T.stores = T._pick ? [...$("sl").querySelectorAll("input:checked")].map(x => x.value) : "all";
        if (T.stores !== "all" && !T.stores.length) return toast("请选择门店"); step = 2; draw(); };
    } else if (step === 2) {
      $("bd").innerHTML = `<div class="card"><h2>2. 盘点项目</h2>
        <div class="f"><label>品项</label><div class="seg" id="ir"><button data-v="all" class="${T.items === "all" ? "on" : ""}"><b>全部品项</b><span>${META.items.length} 项</span></button><button data-v="pick" class="${T.items !== "all" ? "on" : ""}"><b>指定品项</b><span>例：只盘高价设备</span></button></div></div>
        <div id="il" class="${T.items === "all" ? "hide" : ""} f"><div class="chk">${META.items.map(i => `<label><input type="checkbox" value="${i.id}" ${T.items !== "all" && T.items.includes(i.id) ? "checked" : ""}>${esc(i.name)}</label>`).join("")}</div></div>
        <div class="f"><label>方式</label><div class="seg" id="md"><button data-v="full" class="${T.mode === "full" ? "on" : ""}"><b>全盘</b><span>范围内每件都盘</span></button><button data-v="sample" class="${T.mode === "sample" ? "on" : ""}"><b>抽盘</b><span>每店随机抽 <input id="pct" type="number" value="${T.pct}" min="5" max="100" style="width:56px;padding:2px 6px;font-size:13px;display:inline-block">%</span></button></div></div>
        <div class="f"><label>照片要求</label><div class="chips" id="ph">${[["each","每件拍照（含标签）"],["none","不需拍照"]].map(([k, t]) => `<button type="button" data-v="${k}" class="${k === T.photo ? "on" : ""}">${t}</button>`).join("")}</div></div>
        <label style="display:flex;gap:8px;align-items:center;color:var(--ink);margin-bottom:8px"><input type="checkbox" id="ai" ${T.ai ? "checked" : ""}> AI 检查照片（品项、标签编号、翻拍、重复照片）</label>
        <label style="display:flex;gap:8px;align-items:center;color:var(--ink)"><input type="checkbox" id="lk" ${T.lock ? "checked" : ""}> 盘点期间，范围内资产的调拨 / 报废审批暂停</label>
        <div class="aimsg skip" id="pvw" style="margin-top:12px">计算中…</div></div>${nav()}`;
      let ip = T.items !== "all";
      $("ir").querySelectorAll("button").forEach(b => b.onclick = () => { ip = b.dataset.v === "pick"; $("ir").querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b)); $("il").classList.toggle("hide", !ip); upd(); });
      $("md").querySelectorAll("button").forEach(b => b.onclick = ev => { if (ev.target.id === "pct") return; T.mode = b.dataset.v; $("md").querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b)); upd(); });
      $("ph").querySelectorAll("button").forEach(b => b.onclick = () => { T.photo = b.dataset.v; $("ph").querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b)); });
      const read = () => { T.items = ip ? [...$("il").querySelectorAll("input:checked")].map(x => +x.value) : "all"; T.pct = +$("pct").value || 20; T.ai = $("ai").checked; T.lock = $("lk").checked; };
      const upd = () => { read(); if (T.items !== "all" && !T.items.length) { $("pvw").textContent = "请选择品项"; return; }
        api("/api/asset/count/preview", {method:"POST", body:T}).then(d => { T._n = d.sampled; $("pvw").innerHTML = `范围内在用资产 <b>${d.total}</b> 件，本次要盘 <b>${d.sampled}</b> 件、<b>${d.stores.length}</b> 家门店`; }).catch(e => $("pvw").textContent = e.message); };
      $("il").querySelectorAll("input").forEach(x => x.onchange = upd); $("pct").onchange = upd; upd();
      $("pv").onclick = () => { read(); step = 1; draw(); };
      $("nx").onclick = () => { read(); if (T.items !== "all" && !T.items.length) return toast("请选择品项"); step = 3; draw(); };
    } else if (step === 3) {
      $("bd").innerHTML = `<div class="card"><h2>3. 执行与期限</h2>
        <div class="f"><label>执行人</label><div class="aimsg skip" style="margin:0">各门店店长（门店账号）用手机拍照盘点</div></div>
        <div class="f"><label>复核人</label><div class="aimsg skip" style="margin:0">资产管理员（${esc(me().name)}）</div></div>
        <div class="g2 f"><div><label>开始日期</label><input type="date" id="sd" value="${T.start_date}"></div><div><label>门店完成期限</label><input type="date" id="ed" value="${T.end_date}"></div></div>
        <div class="f"><label>复核完成日期</label><input type="date" id="rd" value="${T.review_date}"></div>
        <label style="display:flex;gap:8px;align-items:center;color:var(--ink);margin-bottom:12px"><input type="checkbox" id="rm" ${T.remind ? "checked" : ""}> 门店首页提醒，逾期标红</label>
        <div class="f"><label>给门店的说明（选填）</label><textarea id="nt" placeholder="例：仓库与后场设备也要盘">${esc(T.note)}</textarea></div></div>${nav()}`;
      const read = () => Object.assign(T, {start_date:$("sd").value, end_date:$("ed").value, review_date:$("rd").value, remind:$("rm").checked, note:$("nt").value.trim()});
      $("pv").onclick = () => { read(); step = 2; draw(); };
      $("nx").onclick = () => { read(); if (!T.end_date) return toast("请选择完成期限"); if (T.end_date < T.start_date) return toast("期限不能早于开始日期"); if (T.review_date < T.end_date) return toast("复核日期不能早于门店期限"); step = 4; draw(); };
    } else {
      const sn = T.stores === "all" ? `全部门店（${META.stores.length} 家）` : T.stores.map(stName).join("、");
      const it = T.items === "all" ? "全部品项" : T.items.map(i => (META.items.find(x => x.id === i) || {}).name).join("、");
      $("bd").innerHTML = `<div class="card"><h2>4. 确认发起</h2>
        <div class="mr"><span class="note">任务</span><b>${esc(T.name)}</b></div><div class="mr"><span class="note">类型</span><span>${esc(T.ctype)}</span></div>
        <div class="mr"><span class="note">门店</span><span style="text-align:right">${esc(sn)}</span></div><div class="mr"><span class="note">品项</span><span style="text-align:right">${esc(it)}</span></div>
        <div class="mr"><span class="note">方式</span><span>${T.mode === "full" ? "全盘" : "抽盘 " + T.pct + "%"} · 约 ${T._n ?? "—"} 件</span></div>
        <div class="mr"><span class="note">照片 / AI</span><span>${T.photo === "each" ? "每件拍照" : "不需拍照"} · ${T.ai ? "AI 检查" : "不检查"}</span></div>
        <div class="mr"><span class="note">期限</span><span>${T.start_date} ～ ${T.end_date}，复核 ${T.review_date}</span></div>
        ${T.lock ? `<div class="aimsg doubt" style="margin-top:8px">发起后，范围内资产的调拨 / 报废审批会暂停到结案。</div>` : ""}</div>${nav(true)}`;
      $("pv").onclick = () => { step = 3; draw(); };
      $("nx").onclick = e => run(e.currentTarget, async () => { const r = await api("/api/asset/count", {method:"POST", body:T}); toast(`已发起，共 ${r.n} 件`); location.replace("#count?id=" + r.id); });
    }
  };
  draw();
}

async function adminCount(){
  const id = +qparam("id");
  let store = qparam("store") || "";
  shell("盘点进度", "资产管理员", true, `<div id="bd"><div class="empty">载入中…</div></div>`);
  const load = async () => {
    await meta();
    const d = await api("/api/asset/count/detail?" + qs({id, store}));
    const t = d.task, p = t.progress, open = t.status === "open";
    let h = `<div class="card"><h2>${esc(t.name)} ${badge(open ? (t.overdue ? "fail" : "pending") : t.status === "closed" ? "done" : "cancelled", t.overdue ? "已逾期" : t.status_text)}</h2>
      <div class="note">${esc(t.ctype)} · ${t.mode === "sample" ? `抽盘 ${t.rules.pct}%` : "全盘"} · ${esc(t.start_date)} ～ ${esc(t.end_date)} · 复核 ${esc(t.review_date)}</div>
      <div class="prog"><i style="width:${p.n ? 100 * p.done / p.n : 0}%"></i></div>
      <div class="row sb note"><span>已盘 ${p.done}/${p.n}</span><span>符合 ${p.ok} · 存疑 ${p.doubt} · 找不到 ${p.missing} · 盘盈 ${p.extra}</span></div>
      ${t.status === "closed" ? `<div class="aimsg ok" style="margin-top:8px">已结案：盘亏 ${t.summary.lost} 件（${yen(t.summary.lostValue)}）、盘盈入账 ${t.summary.added} 件、状况更新 ${t.summary.condChanged} 件</div>` : ""}
      <div class="row end" style="margin-top:8px"><button class="btn sm sec" id="rp">导出盘点报告</button>${open ? `<button class="btn sm redo" id="cn">取消任务</button><button class="btn sm" id="cl">结案</button>` : ""}</div></div>`;
    h += `<div class="card"><h2>门店进度 ${d.toReview ? badge("pending", d.toReview + " 件待复核") : ""}</h2>${d.stores.map(s => `<div class="al" data-s="${esc(s.store)}" style="${s.store === store ? "background:var(--gl);border-radius:10px;padding-left:8px" : ""}"><span class="t"><b>${esc(s.name)}</b><small>已盘 ${s.progress.done}/${s.progress.n} · 找不到 ${s.progress.missing} · 盘盈 ${s.progress.extra}${s.submitted ? " · 已提交" : ""}</small><div class="prog" style="margin:4px 0 0"><i style="width:${s.progress.n ? 100 * s.progress.done / s.progress.n : 0}%"></i></div></span>${s.toReview ? badge("pending", s.toReview + " 待复核") : s.submitted ? badge("done", "已提交") : badge("todo", "进行中")}</div>`).join("")}</div>`;
    if (store && d.lines) {
      const ord = {missing:0, extra:1, fail:2, doubt:3, todo:4, ok:5};
      const ls = d.lines.slice().sort((a, b) => (ord[a.status] - ord[b.status]) || String(a.asset_no).localeCompare(b.asset_no));
      h += `<div class="card"><h2>${esc(d.store.name)} 明细</h2>${ls.map(l => `<div class="rec"><div class="l1"><span>${esc(l.name)} <span class="note" style="font-weight:400">${esc(l.asset_no || "无标签")}</span></span>${badge(l.status, l.status_text)}</div>
        ${l.cond ? `<div class="meta">状况：${esc(l.cond)}${l.at ? " · " + ts(l.at) : ""}</div>` : ""}${l.note ? `<div class="meta">门店说明：${esc(l.note)}</div>` : ""}
        ${l.ai && l.ai.verdict && l.ai.verdict !== "skip" ? aiMsg(l.ai) : ""}${thumbs(l.photos)}
        ${l.review ? `<div class="ev">复核：${esc(l.review_text)}${l.review_note ? "，" + esc(l.review_note) : ""}</div>` : ""}
        ${open && ["missing", "extra", "doubt", "fail"].includes(l.status) ? `<div class="acts">${l.status === "missing" ? `<button class="btn sm redo" data-r="lost" data-i="${l.id}">确认盘亏</button>` : ""}${l.status === "extra" ? `<button class="btn sm" data-r="add" data-i="${l.id}">盘盈入账</button><button class="btn sm sec" data-r="ignore" data-i="${l.id}">不处理</button>` : `<button class="btn sm sec" data-r="recount" data-i="${l.id}">退回重盘</button><button class="btn sm" data-r="pass" data-i="${l.id}">通过</button>`}</div>` : ""}
        ${open && l.status === "ok" ? `<div class="acts"><button class="btn link sm" data-r="recount" data-i="${l.id}">退回重盘</button></div>` : ""}</div>`).join("")}</div>`;
    }
    $("bd").innerHTML = h;
    $("rp").onclick = () => download("/api/asset/export?kind=count&task=" + id);
    $("bd").querySelectorAll("[data-s]").forEach(x => x.onclick = () => { store = x.dataset.s; history.replaceState(null, "", "#count?id=" + id + "&store=" + store); run(null, load); });
    $("bd").querySelectorAll("[data-r]").forEach(b => b.onclick = async () => {
      let note = "";
      if (b.dataset.r === "recount" || b.dataset.r === "lost") { const r = await ask({title:b.dataset.r === "lost" ? "确认盘亏" : "退回门店重盘", input:true, placeholder:b.dataset.r === "lost" ? "说明（例：确认遗失）" : "退回原因，门店会看到", ok:"确定", danger:b.dataset.r === "lost"}); if (!r.ok) return; note = r.value; }
      run(b, async () => { await api("/api/asset/count/review", {method:"POST", body:{ids:[+b.dataset.i], act:b.dataset.r, note}}); load(); });
    });
    const cn = $("cn"); if (cn) cn.onclick = async () => { if (!(await ask({text:"取消这个盘点任务？门店的盘点资料会保留但不会结案。", ok:"取消任务", danger:true})).ok) return;
      run(cn, async () => { await api("/api/asset/count/close", {method:"POST", body:{id, cancel:true}}); toast("已取消"); load(); }); };
    const cl = $("cl"); if (cl) cl.onclick = () => closeSheetCount(t, d, load);
  };
  run(null, load);
}

function closeSheetCount(t, d, after){
  const p = t.progress, left = p.n - p.done;
  const sh = openSheet(`<h3>结案：${esc(t.name)}</h3>
    <div class="card" style="padding:12px"><div class="mr"><span class="note">已盘</span><b>${p.done}/${p.n}</b></div><div class="mr"><span class="note">找不到 / 盘盈</span><span>${p.missing} / ${p.extra}</span></div><div class="mr"><span class="note">待复核</span><span>${d.toReview}</span></div></div>
    ${left ? `<div class="f"><label>还有 ${left} 件未盘，处理方式</label><div class="chips" id="td"><button class="on" data-v="keep">维持在用</button><button data-v="lost">视为盘亏</button></div></div>` : ""}
    <ul class="note" style="padding-left:18px;margin:0 0 12px"><li>确认盘亏的资产 → 状态改为「盘亏」</li><li>盘盈入账 → 自动编号建立资产（需目录有这个品项）</li><li>门店回报的状况（闲置、损坏待修）会更新到资产</li><li>每件资产履历加上本次盘点记录</li><li>调拨 / 报废审批恢复</li></ul>
    ${d.toReview ? `<div class="aimsg doubt">还有 ${d.toReview} 笔未复核：找不到的维持在用、盘盈的不入账。</div>` : ""}
    <div class="g2"><button class="btn sec" id="x">取消</button><button class="btn" id="ok">确认结案</button></div>`);
  let todo = "keep";
  sh.querySelectorAll("#td button").forEach(b => b.onclick = () => { todo = b.dataset.v; sh.querySelectorAll("#td button").forEach(x => x.classList.toggle("on", x === b)); });
  sh.querySelector("#x").onclick = closeSheet;
  sh.querySelector("#ok").onclick = e => run(e.currentTarget, async () => { const r = await api("/api/asset/count/close", {method:"POST", body:{id:t.id, opts:{todo, force:true}}}); closeSheet(); toast(`已结案：盘亏 ${r.summary.lost} 件、盘盈入账 ${r.summary.added} 件`); after(); });
}

// ---------------------------------------------------------------- 设定
async function adminSettings(){
  shell("资产设定", "资产管理员", true, `<div id="bd"><div class="empty">载入中…</div></div>`);
  run(null, async () => {
    const d = await api("/api/asset/settings"), s = d.settings, lock = d.demo;
    const sec = (k, set) => `<input id="${k}" type="password" autocomplete="new-password" placeholder="${set ? "已设定（留空 = 不修改）" : "未设定"}" ${lock ? "disabled" : ""}>`;
    $("bd").innerHTML = `<div class="card"><h2>资产编号</h2><div class="g2 f"><div><label>前缀</label><input id="asset_no_prefix" value="${esc(s.asset_no_prefix)}"></div><div><label>购入逾期提醒（天）</label><input id="stockin_overdue_days" inputmode="numeric" value="${esc(s.stockin_overdue_days)}"></div></div>
        <p class="note" style="margin:0">规则：前缀-品项代码-年份-4位流水号，例：${esc(s.asset_no_prefix)}-ZB-${today().slice(0,4)}-0031</p></div>
      <div class="card"><h2>照片储存 · 阿里云 OSS</h2>${lock ? `<div class="aimsg doubt">演示版不能设定金钥，照片存在演示伺服器。</div>` : ""}
        <div class="g2 f"><div><label>地域</label><input id="oss_region" value="${esc(s.oss_region)}" ${lock ? "disabled" : ""}></div><div><label>Bucket 名称</label><input id="oss_bucket" value="${esc(s.oss_bucket)}" ${lock ? "disabled" : ""}></div></div>
        <div class="f"><label>AccessKey ID</label><input id="oss_ak_id" value="${esc(s.oss_ak_id)}" autocomplete="off" ${lock ? "disabled" : ""}></div>
        <div class="f"><label>AccessKey Secret</label>${sec("oss_ak_secret", s.oss_ak_secret_set)}</div>
        <p class="note" style="margin:0">未设定前，照片先存在伺服器（目前 ${d.photos.local} 张）；设定后新照片直接上传 OSS，失败的会自动补传（待补传 ${d.photos.pending} 张）。</p></div>
      <div class="card"><h2>AI 照片检测 · 阿里云百炼</h2>
        <div class="f"><label>API-KEY</label>${sec("ai_key", s.ai_key_set)}</div>
        <div class="f"><label>模型</label>${sel("ai_model", [["qwen-vl-plus","qwen-vl-plus（建议，便宜）"],["qwen-vl-max","qwen-vl-max（较准、较贵）"]], s.ai_model)}</div>
        <p class="note" style="margin:0">未设定时照片照常上传，只是不做 AI 检查（重复照片检查仍有效）。</p></div>
      <div class="g2"><button class="btn sec" id="ts">测试连线</button><button class="btn" id="sv">保存</button></div><div id="tr" style="margin-top:12px"></div>`;
    $("sv").onclick = e => run(e.currentTarget, async () => {
      const b = {}; ["asset_no_prefix", "stockin_overdue_days", "ai_model", ...(lock ? [] : ["oss_region", "oss_bucket", "oss_ak_id", "oss_ak_secret"])].forEach(k => b[k] = $(k).value.trim());
      if (!lock) b.ai_key = $("ai_key").value.trim();
      await api("/api/asset/settings", {method:"POST", body:{settings:b}}); toast("已保存"); META = null; adminSettings(); });
    $("ts").onclick = e => run(e.currentTarget, async () => { const r = await api("/api/asset/settings/test", {method:"POST", body:{}}); $("tr").innerHTML = `<div class="aimsg skip">${esc(r.oss)}<br>${esc(r.ai)}</div>`; });
  });
}

// ================================================================ 财务
async function finHome(){
  shell("资产购入", me().name + " · 财务", false, `<button class="btn hero" id="nw">＋ 发起购入<span>选品项、数量、分配门店；门店到货后拍照入库</span></button><div style="height:12px"></div>
    <div id="hk"></div><div class="card"><h2>购入记录 <button class="btn sm sec" id="ex">导出</button></h2><div id="ls"><div class="empty">载入中…</div></div></div>`);
  $("nw").onclick = () => go("#new");
  $("ex").onclick = () => download("/api/asset/export?kind=purchases");
  run(null, async () => {
    const d = await api("/api/asset/fin/home");
    $("hk").innerHTML = `<div class="kpis"><div class="kpi"><div>本月购入</div><b>${d.monthQty}</b> <span class="note">件</span></div><div class="kpi"><div>本月金额</div><b style="font-size:19px">${yen(d.monthAmount)}</b></div></div>
      ${d.pending ? `<div class="banner info" style="cursor:default"><span>有 <b>${d.pending}</b> 件购入资产等待门店入库</span></div>` : ""}`;
    $("ls").innerHTML = d.purchases.map(p => `<div class="rec"><div class="l1"><span>${esc(p.name)} × ${p.qty}</span>${p.done === p.qty ? badge("done", "已全部入库") : p.refused ? badge("refused", `拒收 ${p.refused}`) : badge("shipped", `入库 ${p.done}/${p.qty}`)}</div>
      <div class="route">${yen(p.price)} × ${p.qty} = <b>${yen(p.price * p.qty)}</b></div>
      <div class="meta">${Object.entries(p.alloc).map(([k, v]) => esc(k) + " " + v).join("、")}</div>
      <div class="meta">购入 ${esc(p.buy_date)}${p.expect_date ? " · 预计到货 " + esc(p.expect_date) : ""} · ${esc(p.created_name)}</div>
      ${p.note ? `<div class="meta">备注：${esc(p.note)}</div>` : ""}${p.issue ? `<div class="ev red">${p.issue} 件到货有状况</div>` : ""}${p.notes.length ? `<div class="ev">${p.notes.map(esc).join("；")}</div>` : ""}</div>`).join("") || `<div class="empty">还没有购入记录</div>`;
  });
}

async function finNew(){
  shell("发起购入", "财务", true, `<div id="bd"><div class="empty">载入中…</div></div>`);
  await run(null, () => meta(true));
  const alloc = {};
  $("bd").innerHTML = `<div class="card"><h2>购入资料</h2>
      <div class="f"><label>品项</label>${sel("it", itemOpts(), "", "请选择")}</div>
      <div class="g2 f"><div><label>单价（元，默认目录价，可改）</label><input id="pr" inputmode="decimal"></div><div><label>购入日期</label><input type="date" id="bd2" value="${today()}"></div></div>
      <div class="g2 f"><div><label>预计到货日期</label><input type="date" id="ex"></div><div><label>备注（选填）</label><input id="nt" placeholder="例：门店扩产"></div></div></div>
    <div class="card"><h2>分配门店与数量 <span class="note" id="tt"></span></h2>${META.stores.map(s => `<div class="al" style="cursor:default"><span class="t"><b>${esc(s.name)}</b><small>${esc(s.code)}</small></span><span class="row" style="flex-wrap:nowrap"><button class="btn sm sec" data-m="${esc(s.code)}">−</button><input data-q="${esc(s.code)}" inputmode="numeric" value="" placeholder="0" style="width:56px;text-align:center;padding:7px 4px"><button class="btn sm sec" data-p="${esc(s.code)}">＋</button></span></div>`).join("")}</div>
    <div class="card" id="pvw"></div>
    <div class="bar2"><span class="note" id="sm"></span><button class="btn" id="go">确认购入</button></div>`;
  const upd = () => {
    const it = META.items.find(i => i.id === +$("it").value), qty = Object.values(alloc).reduce((a, b) => a + b, 0), pr = $("pr").value === "" ? (it ? it.price : 0) : +$("pr").value;
    $("tt").textContent = qty ? `共 ${qty} 件` : "";
    $("sm").innerHTML = qty && it ? `${qty} 件 · <b>${yen(pr * qty)}</b>` : "";
    $("pvw").innerHTML = it && qty ? `<h2>确认后系统会</h2><ul class="note" style="padding-left:18px;margin:0"><li>自动编号 ${qty} 件：${esc(META.prefix)}-${esc(it.code)}-${$("bd2").value.slice(0, 4)}-xxxx</li><li>产生资产标签（资产管理员可列印，随货寄出）</li><li>通知门店：到货后贴标签、拍照入库${META.aiOn ? "（AI 检查）" : ""}</li><li>逾期未入库会提醒资产管理员</li></ul>` : `<div class="note">选择品项与数量后显示</div>`;
  };
  $("it").onchange = () => { const it = META.items.find(i => i.id === +$("it").value); $("pr").placeholder = it ? String(it.price) : ""; upd(); };
  ["pr", "bd2"].forEach(i => $(i).oninput = upd);
  $("bd").querySelectorAll("[data-q]").forEach(x => x.oninput = () => { alloc[x.dataset.q] = Math.max(0, parseInt(x.value) || 0); upd(); });
  const bump = (c, d) => { alloc[c] = Math.max(0, (alloc[c] || 0) + d); $("bd").querySelector(`[data-q="${c}"]`).value = alloc[c] || ""; upd(); };
  $("bd").querySelectorAll("[data-m]").forEach(b => b.onclick = () => bump(b.dataset.m, -1));
  $("bd").querySelectorAll("[data-p]").forEach(b => b.onclick = () => bump(b.dataset.p, 1));
  $("go").onclick = e => {
    const list = Object.entries(alloc).filter(([k, v]) => v > 0).map(([store, qty]) => ({store, qty}));
    if (!$("it").value) return toast("请选择品项"); if (!list.length) return toast("请分配门店与数量");
    run(e.currentTarget, async () => {
      const r = await api("/api/asset/purchase", {method:"POST", body:{item_id:+$("it").value, price:$("pr").value, buy_date:$("bd2").value, expect_date:$("ex").value, note:$("nt").value.trim(), alloc:list}});
      await ask({title:"已建立购入", text:`共 ${r.nos.length} 件，编号 ${r.nos[0]}${r.nos.length > 1 ? " ～ " + r.nos[r.nos.length - 1] : ""}。门店会收到入库通知。`, ok:""});
      go("#");
    });
  };
  upd();
}

window.ASSETS = {
  routes(role){
    init();
    if (role === "store") return {"a":storeHome, "a-list":storeList, "a-apply":storeApply, "a-count":storeCount};
    if (role === "asset") return {"":adminHome, approvals:adminApprovals, assets:adminAssets, catalog:adminCatalog, import:adminImport, counts:adminCounts, "count-new":adminCountNew, count:adminCount, asettings:adminSettings};
    if (role === "finance") return {"":finHome, "new":finNew};
    return {};
  }
};
})();
