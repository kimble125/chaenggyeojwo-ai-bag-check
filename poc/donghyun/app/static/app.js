const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const WD = ["일", "월", "화", "수", "목", "금", "토"];
const SRC = { notice: "통신문", ai: "AI 추천", weather: "날씨", user: "직접" };
const SAMPLE_URL = "https://www.goesn.kr/geumbit-e/na/ntt/selectNttInfo.do?mi=11070&nttSn=1960804&bbsId=10531";

const pad = (n) => String(n).padStart(2, "0");
const ymd = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const today = () => ymd(new Date());
const parse = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
const dday = (s) => Math.round((parse(s) - parse(today())) / 86400000);
const ddayLabel = (n) => (n === 0 ? "오늘" : n === 1 ? "내일" : n > 0 ? `D-${n}` : `${-n}일 전`);

async function api(path, opt = {}) {
  const r = await fetch(path, opt.body && !(opt.body instanceof FormData)
    ? { ...opt, headers: { "Content-Type": "application/json" }, body: JSON.stringify(opt.body) } : opt);
  if (!r.ok) {
    let m = r.statusText;
    try { m = (await r.json()).detail || m; } catch {}
    throw new Error(m);
  }
  return r.json();
}

function toast(msg, ms = 2600) {
  const t = $("#toast");
  t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.add("hidden"), ms);
}

/* ---------- 탭 ---------- */
function show(view) {
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
  $$(".tabbar button").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  if (view === "home") renderHome();
  if (view === "cal") renderCal();
  if (view === "noti") renderNoti();
  window.scrollTo(0, 0);
}
$$(".tabbar button").forEach((b) => b.addEventListener("click", () => show(b.dataset.view)));

/* ---------- 오늘 ---------- */
function wxShort(w) {
  if (!w || w.status !== "ok") return "";
  let s = `${w.weather} · 비 ${rainText(w)} · ${Math.round(w.t_min)}~${Math.round(w.t_max)}°C`;
  const g = worstGrade(w);
  if (g) s += ` · 미세먼지 ${g}`;
  return s;
}
function rainText(w) {
  const p = w.rain_prob_window ?? w.rain_prob;
  return p != null ? `${p}%` : `${w.rain_mm_window ?? w.rain_mm ?? 0}mm`;
}
function worstGrade(w) {
  const order = ["좋음", "보통", "나쁨", "매우나쁨"];
  const gs = [w.pm10_grade, w.pm25_grade].filter(Boolean);
  return gs.length ? gs.sort((a, b) => order.indexOf(b) - order.indexOf(a))[0] : null;
}

function evCard(ev) {
  const d = parse(ev.date), n = dday(ev.date);
  const done = ev.items.filter((i) => i.checked).length, total = ev.items.length;
  const wxItems = ev.items.filter((i) => i.source === "weather").map((i) => i.name);
  return `<button class="ev" data-id="${ev.id}">
    <div class="d"><small>${d.getMonth() + 1}월</small><b>${d.getDate()}</b><small>${WD[d.getDay()]}</small></div>
    <div>
      <h3>${esc(ev.title)}</h3>
      <div class="meta">${[ev.start_time && `${ev.start_time}${ev.end_time ? "–" + ev.end_time : ""}`, ev.location].filter(Boolean).map(esc).join(" · ")}</div>
      <div class="badges">
        <span class="badge dday">${ddayLabel(n)}</span>
        ${ev.kind === "deadline" ? '<span class="badge deadline">회신 마감</span>' : ""}
        ${wxItems.map((x) => `<span class="badge wx">${esc(x)}</span>`).join("")}
      </div>
      ${total ? `<div class="bar" title="준비물 ${done}/${total}"><i style="width:${(done / total) * 100}%"></i></div>` : ""}
    </div></button>`;
}
function bindCards(root) { $$(".ev", root).forEach((b) => b.addEventListener("click", () => openSheet(+b.dataset.id))); }

async function renderHome() {
  const t = today();
  const end = ymd(new Date(Date.now() + 60 * 86400000));
  const evs = await api(`/api/events?start=${t}&end=${end}`);
  const tm = ymd(new Date(Date.now() + 86400000));
  // 저녁 6시 이후엔 내일 가방, 그 전엔 오늘 가방을 크게 보여줌
  const focusDay = new Date().getHours() >= 18 || !evs.some((e) => e.date === t) ? tm : t;
  const focus = evs.filter((e) => e.date === focusDay);
  const label = focusDay === t ? "오늘" : "내일";
  if (focus.length) {
    const items = focus.flatMap((e) => e.items);
    const w = focus.find((e) => e.weather?.status === "ok")?.weather;
    $("#tomorrowCard").innerHTML = `<div class="hero" data-id="${focus[0].id}">
      <div class="k">${label} 챙길 것 · ${items.filter((i) => i.checked).length}/${items.length}</div>
      <h2>${focus.map((e) => esc(e.title)).join(", ")}</h2>
      <div class="bag">${items.map((i) => `<span class="${i.checked ? "done" : ""}">${esc(i.name)}</span>`).join("") || "<span>준비물 없음</span>"}</div>
      ${w ? `<div class="wx">${esc(wxShort(w))}</div>` : ""}
      ${focus.find((e) => e.kind !== "deadline" && e.items.length) ? `<a class="hero-kid" href="/kid?e=${focus.find((e) => e.kind !== "deadline" && e.items.length).id}">🧒 아이랑 가방 싸기 ›</a>` : ""}</div>`;
    $(".hero").addEventListener("click", (e) => { if (!e.target.closest(".hero-kid")) openSheet(focus[0].id); });
  } else {
    $("#tomorrowCard").innerHTML = `<div class="hero calm"><div class="k">${label}</div><h2>${label}은 챙길 학교 일정이 없어요</h2>
      <div class="bag"><span>가정통신문이 오면 ＋ 에서 넣어 주세요</span></div></div>`;
  }
  const rest = evs.filter((e) => e.date !== focusDay);
  $("#upcoming").innerHTML = rest.map(evCard).join("") || `<div class="empty">다가오는 일정이 없어요</div>`;
  bindCards($("#upcoming"));
}

/* ---------- 캘린더 ---------- */
let calMonth = new Date(); calMonth.setDate(1);
let selDay = today();
async function renderCal() {
  const y = calMonth.getFullYear(), m = calMonth.getMonth();
  $("#monthLabel").textContent = `${y}년 ${m + 1}월`;
  const first = new Date(y, m, 1), start = new Date(y, m, 1 - first.getDay());
  const cells = [...Array(42)].map((_, i) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + i));
  const evs = await api(`/api/events?start=${ymd(cells[0])}&end=${ymd(cells[41])}`);
  const byDay = {};
  evs.forEach((e) => (byDay[e.date] ||= []).push(e));
  $("#calGrid").innerHTML = WD.map((w) => `<div class="wd">${w}</div>`).join("") + cells.map((d) => {
    const k = ymd(d), list = byDay[k] || [];
    return `<button data-d="${k}" class="${d.getMonth() !== m ? "out" : ""} ${k === today() ? "today" : ""} ${k === selDay ? "sel" : ""}">
      <b>${d.getDate()}</b><i>${list.slice(0, 3).map((e) => `<u class="${e.kind}"></u>`).join("")}</i></button>`;
  }).join("");
  $$("#calGrid button").forEach((b) => b.addEventListener("click", () => { selDay = b.dataset.d; renderCal(); }));
  const sd = parse(selDay);
  $("#dayLabel").textContent = `${sd.getMonth() + 1}월 ${sd.getDate()}일 (${WD[sd.getDay()]})`;
  $("#dayList").innerHTML = (byDay[selDay] || []).map(evCard).join("") || `<div class="empty">일정 없음</div>`;
  bindCards($("#dayList"));
}
$("#prevM").addEventListener("click", () => { calMonth.setMonth(calMonth.getMonth() - 1); renderCal(); });
$("#nextM").addEventListener("click", () => { calMonth.setMonth(calMonth.getMonth() + 1); renderCal(); });

/* ---------- 상세 시트 ---------- */
let sheetId = null;
async function openSheet(id) {
  sheetId = id;
  const ev = await api(`/api/events/${id}`);
  renderSheet(ev);
  $("#sheet").classList.remove("hidden"); $("#sheetBack").classList.remove("hidden");
}
function closeSheet() {
  $("#sheet").classList.add("hidden"); $("#sheetBack").classList.add("hidden"); sheetId = null;
  const v = $(".view.active").id.replace("view-", ""); if (v === "home") renderHome(); if (v === "cal") renderCal();
}
$("#sheetBack").addEventListener("click", closeSheet);

function wxBlock(ev) {
  const w = ev.weather;
  if (!w) return `<p class="hint">날씨 정보를 아직 못 가져왔어요.</p>`;
  if (w.status === "past") return `<p class="hint">지난 일정이라 날씨를 보지 않아요.</p>`;
  if (w.status === "too_far") return `<p class="hint">일정이 ${w.days_ahead}일 뒤라 아직 예보가 없어요. ${w.available_from}일 전부터 자동으로 확인해서 우산·마스크를 넣어 드릴게요.</p>`;
  const p = w.rain_prob_window ?? w.rain_prob, g = worstGrade(w);
  return `<div class="wxbox">
      <div><small>날씨</small><b>${esc(w.weather)}</b><small>${Math.round(w.t_min)}~${Math.round(w.t_max)}°C</small></div>
      ${p != null ? `<div><small>강수확률</small><b>${p}%</b><small>${w.rain_mm ?? 0}mm</small></div>`
        : `<div><small>활동시간 강수</small><b>${w.rain_mm_window ?? 0}mm</b><small>하루 ${w.rain_mm ?? 0}mm</small></div>`}
      <div><small>미세먼지</small><b class="g-${g || ""}">${g || "–"}</b><small>${w.pm10 != null ? `PM10 ${w.pm10}·PM2.5 ${w.pm25}` : esc(w.air_note || "")}</small></div>
    </div><p class="hint">기준: ${esc(w.place || "")} · ${esc(w.provider || "")} · ${esc(w.fetched_at)} 업데이트</p>`;
}

function renderSheet(ev) {
  const d = parse(ev.date);
  const order = { notice: 0, weather: 1, ai: 2, user: 3 };
  const items = [...ev.items].sort((a, b) => order[a.source] - order[b.source]);
  $("#sheet").innerHTML = `<div class="grab"></div>
    <h2>${esc(ev.title)}</h2>
    <div class="info">${d.getMonth() + 1}월 ${d.getDate()}일 (${WD[d.getDay()]}) · ${ddayLabel(dday(ev.date))}
      ${ev.start_time ? ` · ${esc(ev.start_time)}${ev.end_time ? "–" + esc(ev.end_time) : ""}` : ""}
      ${ev.location ? `<br>📍 ${esc(ev.location)}` : ""}${ev.target ? ` · ${esc(ev.target)}` : ""}</div>
    <div class="card">${wxBlock(ev)}
      ${ev.kind !== "deadline" ? `<div class="actions" style="margin-top:4px">
        <button class="ghost small" id="wxRefresh">날씨 다시 확인</button>
        <button class="ghost small" data-sim="rain">시연: 비 온다면?</button>
        <button class="ghost small" data-sim="dust">시연: 미세먼지 나쁨</button></div>` : ""}
      ${ev.weather?.simulated ? `<p class="hint">⚠️ 시연용 가정 날씨예요. '날씨 다시 확인'을 누르면 실제 예보로 돌아가요.</p>` : ""}</div>
    <div class="card">
      <strong>준비물 체크리스트</strong>
      <ul class="checklist">${items.map((i) => `<li>
        <input type="checkbox" data-iid="${i.id}" ${i.checked ? "checked" : ""} aria-label="${esc(i.name)}">
        <span class="nm ${i.checked ? "done" : ""}">${esc(i.name)}${i.reason ? `<span class="why">${esc(i.reason)}</span>` : ""}</span>
        <span class="src ${i.source}">${SRC[i.source]}</span>
        ${i.source !== "weather" ? `<button class="del" data-del="${i.id}" aria-label="삭제">✕</button>` : ""}
      </li>`).join("") || `<li class="hint">준비물이 없어요</li>`}</ul>
      <div class="chip-add"><input id="newItem" placeholder="준비물 직접 추가"><button class="ghost" id="addItem">추가</button></div>
    </div>
    ${ev.notes ? `<div class="card"><strong>메모</strong><div class="notes">${esc(ev.notes)}</div></div>` : ""}
    ${ev.source_url ? `<p class="hint">출처: <a href="${esc(ev.source_url)}" target="_blank" rel="noopener">${esc(ev.source_title || "가정통신문")}</a></p>` : ""}
    ${ev.kind !== "deadline" && ev.items.length ? `<a class="kid-cta" href="/kid?e=${ev.id}">🧒 아이랑 가방 싸기<small>큰 카드로 하나씩 · 사진으로 확인</small></a>` : ""}
    <div class="actions">
      <button class="ghost small" id="testNoti">알림 미리보기</button>
      <button class="ghost small" id="editDate">날짜 바꾸기</button>
      <button class="ghost small danger" id="delEv">일정 삭제</button>
      <button class="ghost small" id="closeSheet" style="margin-left:auto">닫기</button>
    </div>`;
  $$("#sheet input[data-iid]").forEach((c) => c.addEventListener("change", async () => {
    await api(`/api/items/${c.dataset.iid}`, { method: "PATCH", body: { checked: c.checked } });
    c.nextElementSibling.classList.toggle("done", c.checked);
  }));
  $$("#sheet [data-del]").forEach((b) => b.addEventListener("click", async () => {
    await api(`/api/items/${b.dataset.del}`, { method: "DELETE" }); openSheet(ev.id);
  }));
  const add = async () => {
    const v = $("#newItem").value.trim(); if (!v) return;
    await api(`/api/events/${ev.id}/items`, { method: "POST", body: { name: v } }); openSheet(ev.id);
  };
  $("#addItem").addEventListener("click", add);
  $("#newItem").addEventListener("keydown", (e) => e.key === "Enter" && add());
  $("#wxRefresh")?.addEventListener("click", async (e) => {
    e.target.innerHTML = '<span class="spin"></span>'; renderSheet(await api(`/api/events/${ev.id}/weather`, { method: "POST" }));
  });
  $$("#sheet [data-sim]").forEach((b) => b.addEventListener("click", async () => {
    b.innerHTML = '<span class="spin"></span>';
    renderSheet(await api(`/api/events/${ev.id}/weather?simulate=${b.dataset.sim}`, { method: "POST" }));
  }));
  $("#testNoti").addEventListener("click", async () => { await api(`/api/events/${ev.id}/test-notify`, { method: "POST" }); pollNoti(); });
  $("#editDate").addEventListener("click", async () => {
    const v = prompt("새 날짜 (YYYY-MM-DD)", ev.date);
    if (!v || !/^\d{4}-\d{2}-\d{2}$/.test(v)) return;
    renderSheet(await api(`/api/events/${ev.id}`, { method: "PATCH", body: { date: v } }));
    toast("날짜를 바꾸고 날씨를 다시 확인했어요");
  });
  $("#delEv").addEventListener("click", async () => {
    if (!confirm("이 일정을 지울까요?")) return;
    await api(`/api/events/${ev.id}`, { method: "DELETE" }); closeSheet();
  });
  $("#closeSheet").addEventListener("click", closeSheet);
}

/* ---------- 통신문 추가 ---------- */
let src = "url", photos = [], fetched = null, draft = null;
$$(".tab").forEach((t) => t.addEventListener("click", () => {
  src = t.dataset.src;
  $$(".tab").forEach((x) => x.classList.toggle("active", x === t));
  $$(".src").forEach((x) => x.classList.toggle("hidden", x.dataset.src !== src));
}));
$("#sampleBtn").addEventListener("click", () => { $("#urlIn").value = SAMPLE_URL; });
$("#photoIn").addEventListener("change", (e) => {
  photos = [...e.target.files];
  $("#photoPrev").innerHTML = photos.map((f) => `<img src="${URL.createObjectURL(f)}" alt="">`).join("");
});

$("#extractBtn").addEventListener("click", async () => {
  const btn = $("#extractBtn"), st = $("#extractStatus");
  btn.disabled = true; $("#preview").innerHTML = "";
  try {
    const fd = new FormData();
    fetched = null;
    if (src === "url") {
      const url = $("#urlIn").value.trim();
      if (!url) throw new Error("주소를 넣어 주세요");
      st.innerHTML = '<span class="spin"></span> 통신문 가져오는 중…';
      fetched = await api("/api/notice/fetch", { method: "POST", body: { url } });
      fd.append("text", fetched.text); fd.append("title", fetched.title || ""); fd.append("posted", fetched.posted || "");
    } else if (src === "text") {
      const t = $("#textIn").value.trim();
      if (!t) throw new Error("내용을 붙여넣어 주세요");
      fd.append("text", t);
    } else {
      if (!photos.length) throw new Error("사진을 골라 주세요");
      photos.forEach((p) => fd.append("images", p));
    }
    st.innerHTML = '<span class="spin"></span> AI가 일정과 준비물을 읽는 중…';
    const t0 = performance.now();
    const res = await api("/api/notice/extract", { method: "POST", body: fd });
    st.textContent = `${((performance.now() - t0) / 1000).toFixed(1)}초 · ${res.usage.model}`;
    draft = res.events.map((e) => ({ ...e, _on: true }));
    renderPreview(res);
  } catch (e) {
    st.textContent = "⚠️ " + e.message;
  } finally { btn.disabled = false; }
});

function renderPreview(res) {
  const meta = fetched ? `<p class="src-meta"><b>${esc(fetched.title)}</b>${fetched.posted ? ` · ${esc(fetched.posted)}` : ""}
      ${fetched.attachments.length ? `<br>첨부: ${fetched.attachments.map((a) => `<a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.name)}</a>`).join(", ")}` : ""}</p>
      <details class="raw"><summary>가져온 본문 보기</summary><pre>${esc(fetched.text)}</pre></details>` : "";
  if (!draft.length) {
    $("#preview").innerHTML = `<div class="card">${meta}<p>${esc(res.summary)}</p><div class="empty">캘린더에 넣을 일정이 없는 안내문이에요</div></div>`;
    return;
  }
  $("#preview").innerHTML = `<div class="card">${meta}<p style="margin:8px 0 0">${esc(res.summary)}</p>
      <p class="legend">준비물: <b class="n">●</b> 통신문 원문 · <b class="a">●</b> AI 추천 · 날씨(<b class="w">우산·마스크</b>)는 등록 후 자동 확인</p></div>
    ${draft.map((e, i) => `<div class="card pv ${e.kind}" data-i="${i}">
      <div class="head"><input type="checkbox" data-f="_on" ${e._on ? "checked" : ""} aria-label="이 일정 넣기">
        <input class="title-in" data-f="title" value="${esc(e.title)}"></div>
      <div class="grid">
        <label class="lbl">날짜<input type="date" data-f="date" value="${esc(e.date)}"></label>
        <label class="lbl">종류<input value="${e.kind === "deadline" ? "회신 마감" : e.kind === "event" ? "행사" : "안내"}" disabled></label>
        <label class="lbl">시작<input type="time" data-f="start_time" value="${esc(e.start_time || "")}"></label>
        <label class="lbl">끝<input type="time" data-f="end_time" value="${esc(e.end_time || "")}"></label>
        <label class="lbl full">장소<input data-f="location" value="${esc(e.location || "")}"></label>
      </div>
      <div class="chips">${e.items.map((n, j) => `<span class="chip">${esc(n)}<button data-rm="items:${j}" aria-label="빼기">✕</button></span>`).join("")}
        ${e.ai_items.map((a, j) => `<span class="chip ai" title="${esc(a.reason)}">✨ ${esc(a.name)}<button data-rm="ai_items:${j}" aria-label="빼기">✕</button></span>`).join("")}</div>
      <div class="chip-add"><input placeholder="준비물 추가" data-add><button class="ghost" data-addbtn>추가</button></div>
      ${e.notes ? `<p class="hint">${esc(e.notes)}</p>` : ""}
    </div>`).join("")}
    <button class="primary" id="commitBtn">캘린더에 넣기</button>`;

  $$(".pv").forEach((card) => {
    const e = draft[+card.dataset.i];
    $$("[data-f]", card).forEach((inp) => inp.addEventListener("change", () => {
      e[inp.dataset.f] = inp.type === "checkbox" ? inp.checked : inp.value;
    }));
    $$("[data-rm]", card).forEach((b) => b.addEventListener("click", () => {
      const [k, j] = b.dataset.rm.split(":"); e[k].splice(+j, 1); renderPreview(res);
    }));
    const addIn = $("[data-add]", card);
    const add = () => { const v = addIn.value.trim(); if (v) { e.items.push(v); renderPreview(res); } };
    $("[data-addbtn]", card).addEventListener("click", add);
    addIn.addEventListener("keydown", (ev) => ev.key === "Enter" && add());
  });
  $("#commitBtn").addEventListener("click", async () => {
    const evs = draft.filter((e) => e._on);
    if (!evs.length) return toast("넣을 일정을 하나 이상 골라 주세요");
    $("#commitBtn").disabled = true;
    try {
      const r = await api("/api/notice/commit", { method: "POST", body: {
        events: evs, source_title: fetched?.title || null, source_url: fetched?.url || null } });
      toast(`📅 ${r.created.length}개 일정을 캘린더에 넣었어요 (MCP add_event)`);
      $("#preview").innerHTML = ""; $("#extractStatus").textContent = "";
      selDay = r.created[0].date; calMonth = parse(selDay); calMonth.setDate(1);
      show("cal");
    } catch (e) { toast("⚠️ " + e.message); $("#commitBtn").disabled = false; }
  });
}

/* ---------- 알림 ---------- */
async function renderNoti() {
  $("#notiDot").classList.add("hidden");
  const list = await api("/api/notifications");
  $("#notiList").innerHTML = list.map((n) => {
    const [t, ...b] = (n.message || "").split("\n");
    return n.delivered_at
      ? `<div class="noti"><div class="when">${esc(n.delivered_at)}</div><div class="t">${esc(t)}</div><div class="b">${esc(b.join("\n"))}</div></div>`
      : `<div class="noti pending"><div class="when">예약 · ${esc(n.fire_at)}</div><div class="t">${esc(n.event_title)}</div>
         <div class="b">${n.kind === "eve" ? "전날 저녁 가방 싸기 알림" : n.kind === "morning" ? "당일 아침 최종 확인 알림" : "미리보기"}</div></div>`;
  }).join("") || `<div class="empty">아직 알림이 없어요</div>`;
}
$("#permBtn").addEventListener("click", async () => {
  if (!("Notification" in window)) return toast("이 브라우저는 알림을 지원하지 않아요");
  if (!window.isSecureContext) return toast("브라우저 알림은 HTTPS 에서만 돼요.\n앱 안 알림(토스트·🔔)으로 대신 보여드릴게요.");
  const p = await Notification.requestPermission();
  toast(p === "granted" ? "알림을 켰어요" : "알림이 꺼져 있어요");
});
async function pollNoti() {
  try {
    const due = await api("/api/notifications/due");
    for (const n of due) {
      toast(`${n.title}\n${n.body}`, 6000);
      if (window.isSecureContext && "Notification" in window && Notification.permission === "granted") {
        new Notification(n.title, { body: n.body, tag: `n${n.id}` });
      }
      $("#notiDot").classList.remove("hidden");
    }
    if (due.length && $("#view-noti").classList.contains("active")) renderNoti();
  } catch {}
}
setInterval(pollNoti, 30000);

/* ---------- 설정 ---------- */
$("#settingsBtn").addEventListener("click", async () => {
  const { home } = await api("/api/settings");
  $("#homeName").value = home.name; $("#homeLat").value = home.lat; $("#homeLon").value = home.lon;
  $("#settingsDlg").showModal();
});
$("#geoBtn").addEventListener("click", () => {
  if (!navigator.geolocation || !window.isSecureContext) return toast("위치는 HTTPS 에서만 가져올 수 있어요");
  navigator.geolocation.getCurrentPosition((p) => {
    $("#homeLat").value = p.coords.latitude.toFixed(4); $("#homeLon").value = p.coords.longitude.toFixed(4);
    $("#homeName").value = "현재 위치";
  }, () => toast("위치를 가져오지 못했어요"));
});
$("#homeSave").addEventListener("click", async () => {
  await api("/api/settings/home", { method: "PUT", body: { name: $("#homeName").value, lat: $("#homeLat").value, lon: $("#homeLon").value } });
  toast("기본 위치를 저장했어요");
});

/* ---------- 시작 ---------- */
(() => {
  const d = new Date();
  $("#todayLabel").textContent = `${d.getMonth() + 1}월 ${d.getDate()}일 ${WD[d.getDay()]}요일`;
  renderHome(); pollNoti();
})();
