/* 아이 미션: 펼치기 → (추천 고르기) → 사진/하나씩 확인 → (두고 갈 것) → 결과 → 엄마 화면에 남기기 → 스티커판
   돌아오기: kid.html?e=<id>&mode=home
   원칙: 누르는 칸은 크게, 한 화면에 할 일 하나, '다시 빼기'는 눈에 보이게, 다 넣기 전엔 칭찬 없음.
   추가(호연 몫): 추천은 '추천'이라고 따로 보이고 받아들인 것만 센다 / 알림장의 조건·금지는 카드·말소리·결과에 끝까지 남긴다 /
   체크는 서버에 저장된 뒤에만 화면에 반영한다(실패하면 그대로 둔다). */
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const TINTS = ["--t1", "--t2", "--t3", "--t4", "--t5", "--t6"];

// 준비물 이름 → 그림. 위에서부터 먼저 맞는 것.
const ICONS = [
  [/도시락|밥/, "🍱"], [/수저|젓가락|숟가락/, "🥢"], [/간식|과자/, "🍪"], [/과일/, "🍎"],
  [/물티슈|휴지|티슈/, "🧻"], [/물통|텀블러/, "🥤"], [/물|음료|생수/, "💧"],
  [/돗자리|매트/, "🧺"], [/모자/, "🧢"], [/손수건|수건/, "🧣"],
  [/우산/, "☂️"], [/우비|비옷|우의/, "🧥"], [/마스크/, "😷"], [/장갑|핫팩/, "🧤"], [/양말/, "🧦"],
  [/수영복/, "🩱"], [/수경|물안경/, "🥽"], [/도복|띠$/, "🥋"],
  [/반티|티셔츠|체육복|옷|겉옷|점퍼/, "👕"], [/실내화|운동화|신발/, "👟"], [/공연복|한복|드레스/, "👗"],
  [/보조가방|가방|봉투|비닐|봉지/, "🛍️"], [/교재|책|교과서|공책|노트|활동지/, "📚"], [/필기|연필|펜|필통/, "✏️"],
  [/색연필|크레파스|사인펜/, "🖍️"], [/가위/, "✂️"], [/풀/, "🧴"], [/자$|자\b/, "📏"],
  [/멀미|약/, "💊"], [/선크림|썬크림|세면/, "🧴"], [/신청서|회신|동의서|서류/, "📝"],
  [/줄넘기/, "🪢"], [/카메라/, "📷"], [/이름표|명찰/, "🏷️"], [/돈|용돈|카드|지갑/, "🪙"], [/안경/, "👓"],
];
const iconFor = (it) => esc(it.meta?.emoji || (ICONS.find(([re]) => re.test(it.name)) || [, "🎒"])[1]);

// "물(음료)" → 큰 글씨 "물", 작은 글씨 "음료"
function split(name) {
  const m = name.match(/^(.*?)\s*[(（](.+?)[)）]\s*$/);
  return m ? [m[1], m[2]] : [name, ""];
}
const nameOf = (it) => it.meta?.base || split(it.name)[0];
const condOf = (it) => it.meta?.condition || it.meta?.quantity || "";       // 조건이 없으면 수량("한 봉지만")을 보여 준다
const isRec = (it) => ["recommend", "ai", "weather"].includes(it.source);   // 통신문에 없는 것(받아들였어도 출처는 추천)
const isWear = (it) => it.meta?.kind === "wear";
const isOpt = (it) => !!it.optional;
// 날씨 준비물은 아이가 이해할 말로
function kidHint(it) {
  if (it.source === "weather") {
    if (/우산|우비/.test(it.name)) return "비 소식이 있대요";
    if (/마스크/.test(it.name)) return "먼지가 많대요";
    if (/장갑|핫팩|겉옷/.test(it.name)) return "추운 날이에요";
    if (/모자|물/.test(it.name)) return "더운 날이에요";
    return "";
  }
  if (it.meta?.conditional === "rain") return "비가 올 때만";
  if (it.meta?.optional_by_notice) return "가져가도 되고 안 가져가도 돼요";
  return it.meta ? "" : split(it.name)[1];
}
// 말로 읽어 줄 문장: 조건과 안 되는 것까지 읽는다
function speakOf(it) {
  let s = nameOf(it);
  if (condOf(it)) s += `. ${condOf(it)}`;
  if (it.meta?.not_accepted?.length) s += `. ${it.meta.not_accepted.join(", ")}은 안 돼요`;
  return s;
}

let ev = null, plus = null, mode = { demo: false, ai: true }, items = [], queue = [], qi = 0, fromPhoto = false;
let recQ = [], warnQ = [], busy = false, backTo = "s-lay";
let recBudget = 4;                                         // 아이에게 한 번에 묻는 추천은 4개까지(나머지는 부모 화면에)

async function api(path, opt = {}) {
  const r = await fetch(path, opt.json ? { ...opt, headers: { "Content-Type": "application/json" }, body: JSON.stringify(opt.json) } : opt);
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch {} throw Object.assign(new Error(m), { status: r.status }); }
  return r.json();
}
function toast(m, ms = 2600) {
  const t = $("#toast"); t.textContent = m; t.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => (t.hidden = true), ms);
}
function show(id) {
  document.querySelectorAll(".screen").forEach((s) => s.classList.toggle("on", s.id === id));
  window.scrollTo(0, 0);
  renderProg();
}
// 진행 막대: 세는 준비물 가운데 가방에 넣은 수(추천으로만 붙은 것은 세지 않는다)
function renderProg() {
  const box = $("#prog"), on = onScreen();
  const req = ev ? required() : [];
  box.hidden = !req.length || !["s-lay", "s-one", "s-done"].includes(on);
  if (box.hidden) return;
  const n = req.filter((i) => i.checked).length;
  $("#progFill").style.width = `${Math.round((n / req.length) * 100)}%`;
  $("#progText").textContent = `가방 속 ${n} / ${req.length}`;
  box.classList.toggle("full", n === req.length);
}
const onScreen = () => document.querySelector(".screen.on")?.id;
// 한 번에 하나만: 저장하는 동안 다른 버튼을 막는다
async function once(fn) {
  if (busy) return;
  busy = true;
  try { await fn(); } catch (e) { toast("저장을 못 했어요. 다시 눌러 줘요"); } finally { busy = false; }
}

/* ---------- 일정 불러오기 ---------- */
function adopt(v) {
  ev = v; plus = v.plus || null;
  items = v.items.filter((i) => !i.guardian && !i.blocked);   // 보호자가 정할 것(약)과 금지와 겹친 자동 추천은 아이 미션에 넣지 않는다
}
async function load(id) {
  try { adopt(await api(`/api/plus/events/${id}`)); }
  catch (e) {
    if (e.status !== 404 && e.status !== 405) throw e;    // 잠깐의 오류로 금지·보호자 표시를 잃지 않게: 추가 기능이 아예 없는 서버일 때만 기본 일정으로
    adopt(await api(`/api/events/${id}`));
  }
}
const reload = () => load(ev.id);
const required = () => items.filter((i) => !isOpt(i));
const banList = () => plus?.forbidden || [];                                  // 알림장이 가져오지 말라고 한 것(알려 주기만)
const openAlerts = () => banList().filter((f) => f.flagged && !f.removed);    // 사진에 보였는데 아직 안 뺀 것(끝을 막는다)

/* ---------- 읽어 주기 ---------- */
const canSpeak = "speechSynthesis" in window;
function say(text) {
  if (!canSpeak) return;
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "ko-KR"; u.rate = 0.9; u.pitch = 1.1;
  const v = speechSynthesis.getVoices().find((x) => x.lang?.startsWith("ko"));
  if (v) u.voice = v;
  speechSynthesis.speak(u);
}
if (!canSpeak) $("#speakAll").hidden = true;
$("#speakAll").addEventListener("click", () => {
  if (!ev) return say("챙길 게 없어요");
  const on = onScreen();
  if (on === "s-one" && queue[qi]) return say(`${speakOf(queue[qi])}. 가방에 넣었으면 넣었어 버튼을 눌러요.`);
  if (on === "s-rec" && recQ[0]) return say(`${recQ[0].name}. ${recQ[0].why}. 챙길래, 아니면 괜찮아를 눌러요.`);
  if (on === "s-warn" && warnQ[0]) return say($("#warnLead").textContent + ". " + $("#warnWhy").textContent);
  if (on === "s-done") return say($("#doneTitle").textContent + ". " + $("#doneLead").textContent + (banList().length ? `. ${banList().map((f) => f.name).join(", ")}은 두고 가요.` : ""));
  if (on === "s-home") return say($("#homeTitle").textContent + ". " + $("#homeLead").textContent);
  let s = `${$("#layTitle").textContent}. ${items.map(speakOf).join(", ")}. 모두 ${items.length}개를 펼쳐 놓자.`;
  if (banList().length) s += ` ${banList().map((f) => f.name).join(", ")}은 두고 가요.`;
  say(s);
});

/* ---------- 카드 ---------- */
function card(it, i, view) {
  const nm = nameOf(it), hint = kidHint(it), cond = condOf(it);
  const cls = [view === "result" ? (it.checked ? "done" : "todo") : "", isOpt(it) && view !== "result" ? "opt" : ""].join(" ");
  const state = view === "result" ? `<span class="state">${it.checked ? "넣었음" : "아직"}</span>` : "";
  const tag = isRec(it) ? `<span class="tag">추천</span>` : it.meta?.optional_by_notice ? `<span class="tag">선택</span>` : it.meta?.conditional === "rain" ? `<span class="tag">비 올 때</span>` : isWear(it) ? `<span class="tag wear">입고 가요</span>` : "";
  const watch = view !== "result" && (plus?.watch || []).includes(it.name) ? `<span class="tag watch">지난번에 깜빡</span>` : "";
  return `<button class="card ${cls}" data-id="${it.id}" style="--tint:var(${TINTS[i % 6]})" aria-label="${esc(speakOf(it))}${view === "result" ? (it.checked ? " 넣었음" : " 아직") : ""}">
    ${tag}${watch}<span class="ic">${iconFor(it)}</span><span class="nm">${esc(nm)}</span>${cond ? `<span class="cond">${esc(cond)}</span>` : ""}${hint && view !== "result" ? `<span class="hint">${esc(hint)}</span>` : ""}${state}</button>`;
}

// 날씨 한 줄: 예보에서 읽은 것만 말한다(없으면 안 보인다)
function wxLine() {
  const w = ev?.weather;
  if (!w || w.status !== "ok") return "";
  const bits = [];
  if ((w.rain_prob_window ?? w.rain_prob ?? 0) >= 60) bits.push("☔ 비 소식이 있어");
  if (["나쁨", "매우나쁨"].includes(w.pm10_grade) || ["나쁨", "매우나쁨"].includes(w.pm25_grade)) bits.push("😷 먼지가 많아");
  if (w.t_min != null && w.t_min <= 0) bits.push("🧣 많이 추워"); else if (w.t_max != null && w.t_max >= 30) bits.push("🥵 많이 더워");
  if (!bits.length) return "";
  return `${bits.join(" · ")} (${w.simulated ? "가정한 날씨" : "예보"}${w.t_min != null ? ` ${Math.round(w.t_min)}~${Math.round(w.t_max)}°C` : ""})`;
}
/* ---------- 펼치기 ---------- */
function renderLay() {
  const g = $("#layGrid");
  g.innerHTML = items.map((it, i) => card(it, i, "lay")).join("");
  g.querySelectorAll(".card").forEach((b) => b.addEventListener("click", () => {
    const it = items.find((x) => x.id == b.dataset.id);
    b.classList.remove("pop"); void b.offsetWidth; b.classList.add("pop");
    say(speakOf(it));
  }));
  const nReq = required().length, nOpt = items.length - nReq;
  $("#layCount").textContent = nReq || items.length;
  $("#layMore").textContent = nReq && nOpt ? ` · 추천 ${nOpt}개` : "";
  const wx = wxLine(), wl = $("#wxLine");
  wl.hidden = !wx; wl.textContent = wx;
  const ban = banList(), strip = $("#banStrip");
  strip.hidden = !ban.length;
  if (ban.length) strip.innerHTML = `<b>🙅 이건 두고 가요</b>${ban.map((f) => esc(f.name)).join(" · ")}`;
  recQ = (plus?.recs || []).slice(0, Math.max(0, recBudget));
  const bar = $("#recBar");
  bar.hidden = !recQ.length;
  if (recQ.length) bar.innerHTML = `<span style="font-size:30px">✨</span><span>이것도 챙길까? ${recQ.length}개<small>${plus.list_open ? "알림장이 '등'으로 끝나서 더 찾아봤어" : "알림장에는 없지만 있으면 좋은 것"}</small></span>`;
  show("s-lay");
}
$("#banStrip").addEventListener("click", () => {
  const f = banList();
  if (!f.length) return;
  say(`${f.map((x) => x.name).join(", ")}은 두고 가요.`);
  toast(`알림장: “${f[0].evidence}”`, 5000);
});
$("#recBar").addEventListener("click", () => { if (recQ.length) { show("s-rec"); renderRec(); } });
$("#layDone").addEventListener("click", () => $("#photo").click());
$("#noPhoto").addEventListener("click", () => startOne(items.filter((i) => !i.checked), false));
$("#photo").addEventListener("change", (e) => {
  const f = e.target.files[0]; e.target.value = "";
  if (f) photoCheck(f, "");
});
document.querySelectorAll("#demoRow button").forEach((b) => b.addEventListener("click", () => photoCheck(null, b.dataset.case)));

let afterWarn = () => renderDone();
async function photoCheck(file, demoCase) {
  $("#scanImg").src = file ? URL.createObjectURL(file) : "data:image/svg+xml;utf8," + encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="300" height="400"><rect width="300" height="400" fill="#e9e4da"/><text x="150" y="205" font-size="22" text-anchor="middle" fill="#8a8273">예시 사진</text></svg>`);
  show("s-scan");
  await once(async () => {
    let r;
    try {
      const fd = new FormData(); fd.append("image", file || new Blob(["demo"], { type: "image/png" }), "photo.png");
      try { r = await api(`/api/plus/events/${ev.id}/photo-check${demoCase ? `?case=${demoCase}` : ""}`, { method: "POST", body: fd }); }
      catch (e) {                                                    // 옛 사진 확인은 추가 기능이 아예 없는 서버에서만. 크기·횟수·서버 오류는 하나씩으로
        if (!file || plus || (e.status !== 404 && e.status !== 405)) throw e;
        const fd2 = new FormData(); fd2.append("image", file); r = await api(`/api/events/${ev.id}/photo-check`, { method: "POST", body: fd2 });
      }
    } catch (err) {
      toast(err.status === 429 || err.status === 413 ? `${err.message}` : "사진을 못 봤어요. 하나씩 같이 볼까요?", 3500);
      return startOne(items.filter((i) => !i.checked), false);
    }
    if (r.people_or_names) toast("사람이나 이름표가 찍혔어요. 다음엔 물건만 찍어요", 4000);
    try {
      for (const id of r.seen) await setChecked(id, true);          // 사진에 보인 것은 챙긴 것으로 친다(결과 화면에서 다시 뺄 수 있다)
    } catch (err) {                                                  // 저장이 안 됐으면 서버 상태를 다시 받아 하나씩으로
      toast("저장을 못 했어요. 하나씩 같이 볼까요?", 3500);
      try { await reload(); } catch {}
      return startOne(items.filter((i) => !i.checked), false);
    }
    if ((r.forbidden_seen || []).length) await reload();              // 서버가 적어 둔 '보였음' 표시를 받아 온다
    warnQ = (r.forbidden_seen || []).map((n) => banList().find((f) => f.name === n) || { name: n, evidence: "" });
    const rest = items.filter((i) => r.not_seen.includes(i.id) && !i.checked);
    afterWarn = () => startOne(rest, true);
    warnQ.length ? renderWarn() : afterWarn();
  });
}

async function setChecked(id, v) {
  await api(`/api/items/${id}`, { method: "PATCH", json: { checked: v } });   // 저장이 된 뒤에만 화면 상태를 바꾼다
  const it = ev.items.find((x) => x.id === id);
  if (it) it.checked = v;
  renderProg();
}

/* ---------- 추천: 이것도 챙길까? ---------- */
function renderRec() {
  const r = recQ[0];
  if (!r) return renderLay();
  const c = $("#recCard");
  c.className = "big rec in";
  c.innerHTML = `<span class="ic">${esc(r.emoji)}</span><span class="nm">${esc(split(r.name)[0])}</span><span class="hint">${esc(r.why)}</span>`;
  $("#recBasis").textContent = `추천 · ${r.basis}` + (recQ.length > 1 ? ` · ${recQ.length - 1}개 더 있어` : "");
  say(`${split(r.name)[0]}. ${r.why}`);
}
async function answerRec(yes) {
  const r = recQ[0];
  if (!r) return;
  await once(async () => {
    adopt(await api(`/api/plus/events/${ev.id}/recs/${yes ? "accept" : "decline"}`, { method: "POST", json: { name: r.name } }));
    recBudget--;
    recQ = (plus?.recs || []).slice(0, Math.max(0, recBudget));
    recQ.length ? renderRec() : renderLay();
  });
}
$("#recYes").addEventListener("click", () => answerRec(true));
$("#recNo").addEventListener("click", () => answerRec(false));
$("#recBack").addEventListener("click", renderLay);

/* ---------- 두고 갈 것이 보였을 때 ---------- */
function renderWarn() {
  const f = warnQ[0];
  if (!f) return afterWarn();
  $("#warnLead").textContent = `${f.name}이(가) 보여요`;
  $("#warnCard").innerHTML = `<span class="ic">🙅</span><span class="nm">${esc(f.name)}</span><span class="nope">가져가지 않아요</span>`;
  $("#warnWhy").textContent = f.evidence ? `알림장: “${f.evidence}”` : "알림장에서 가져오지 말라고 했어요";
  show("s-warn");
  say(`${f.name}이 보여요. 알림장에서 가져오지 말라고 했어요. 뺐으면 뺐어를 눌러요.`);
}
$("#warnDone").addEventListener("click", () => once(async () => {
  const f = warnQ[0];
  if (f) adopt(await api(`/api/plus/events/${ev.id}/alerts`, { method: "POST", json: { name: f.name, removed: true } }));
  warnQ.shift();                                                     // 저장된 뒤에만 다음 것으로
  renderWarn();
}));
$("#warnAsk").addEventListener("click", () => { warnQ.shift(); renderWarn(); });

/* ---------- 하나씩 ---------- */
function startOne(list, photo) {
  queue = list.map((x) => items.find((i) => i.id === x.id) || x); qi = 0; fromPhoto = photo;
  if (!queue.length) return renderDone();
  show("s-one");
  renderOne();
}
function renderOne() {
  const it = queue[qi], left = queue.length - qi;
  $("#oneTitle").textContent = left === 1 ? "하나만 더 보자" : `${left}개 더 보자`;
  $("#oneLead").textContent = isWear(it) ? "내일 입고 갈 거야" : fromPhoto ? "사진에서 안 보였어. 직접 확인해 보자" : "하나씩 가방에 넣어 보자";
  // 점: 이미 넣은 것(채움) · 지금(굵은 테두리) · 남은 것(점선)
  $("#dots").innerHTML = items.map((x) => `<i class="${x.checked ? "" : x.id === it.id ? "now" : "left"}"></i>`).join("");
  const nm = nameOf(it), hint = kidHint(it), cond = condOf(it), nope = it.meta?.not_accepted || [];
  const big = $("#bigCard");
  big.className = "big in";
  big.innerHTML = `<span class="ic">${iconFor(it)}</span><span class="nm">${esc(nm)}</span>${cond ? `<span class="cond">${esc(cond)}</span>` : ""}` +
    `${nope.length ? `<span class="nope">${esc(nope.join(", "))}은(는) 안 돼요</span>` : ""}${hint ? `<span class="hint">${esc(hint)}</span>` : ""}${isOpt(it) ? `<span class="hint">추천이라 안 넣어도 돼요</span>` : ""}`;
  big.setAttribute("aria-label", speakOf(it));
  $("#bagIcon").classList.remove("show");
  $("#putIn").textContent = isWear(it) ? "꺼내 놨어!" : "넣었어!";
  $("#oneTip").textContent = isWear(it) ? "내일 입을 수 있게 꺼내 놨으면 눌러요" : "눈으로 보고, 가방에 넣었으면 눌러요";
  say(speakOf(it));
}
$("#bigCard").addEventListener("click", () => queue[qi] && say(speakOf(queue[qi])));
$("#putIn").addEventListener("click", () => once(async () => {
  await setChecked(queue[qi].id, true);
  $("#bagIcon").classList.add("show");
  $("#bigCard").classList.replace("in", "drop");
  navigator.vibrate?.(30);
  await new Promise((r) => setTimeout(r, 700));
  next();
}));
$("#notYet").addEventListener("click", () => once(async () => {
  $("#bigCard").classList.replace("in", "skip");
  await new Promise((r) => setTimeout(r, 350));
  next();
}));
function next() { qi++; qi < queue.length ? renderOne() : renderDone(); }

/* ---------- 결과 ---------- */
function renderDone(celebrate = true) {
  const req = required(), opt = items.filter(isOpt);
  const done = req.filter((i) => i.checked), left = req.filter((i) => !i.checked), ban = openAlerts();
  const all = req.length > 0 && left.length === 0 && ban.length === 0;
  $("#s-done").classList.toggle("allclear", all);
  $("#doneTitle").textContent = all ? "다 챙겼지! 🎉" : `${done.length}개 넣었어!`;
  $("#mate-s-done").src = `mascot/ssok_${all ? "star" : ban.length ? "no" : "hello"}.png`;
  let lead = all ? "가방 준비 끝!" : left.length ? `<b>${left.length}</b>개 남았어` : "";
  if (ban.length) lead += `${lead ? " · " : ""}두고 갈 것 <b>${ban.length}</b>개 확인하자`;
  const optLeft = opt.filter((i) => !i.checked).length;
  if (optLeft) lead += `${lead ? " · " : ""}추천 ${optLeft}개는 안 넣었어`;
  $("#doneLead").innerHTML = lead;
  $("#fixAlerts").hidden = !ban.length;
  const allBan = banList(), strip = $("#doneBan");
  strip.hidden = !allBan.length;
  if (allBan.length) strip.innerHTML = `<b>🙅 이건 두고 가요</b>${allBan.map((f) => esc(f.name) + (f.flagged && !f.removed ? " (사진에 보였어)" : "")).join(" · ")}`;
  const g = $("#doneGrid");
  g.innerHTML = items.map((it, i) => card(it, i, "result")).join("");
  g.querySelectorAll(".card").forEach((b) => b.addEventListener("click", () => once(async () => {
    const it = items.find((x) => x.id == b.dataset.id);
    await setChecked(it.id, !it.checked);
    say(it.checked ? `${nameOf(it)} 넣었음` : `${nameOf(it)} 다시 뺐어`);
    renderDone(false);
  })));
  const st = (plus?.stickers || []).length;
  $("#parentNote").innerHTML = `<b>엄마에게:</b> 준비물 ${req.length} · 넣음 ${done.length} · 아직 ${left.length}` +
    (left.length ? ` (${left.map((i) => esc(nameOf(i))).join(", ")})` : "") +
    (opt.length ? ` · 추천 ${opt.length} 중 ${opt.length - optLeft}` : "") +
    (ban.length ? ` · 두고 갈 것 ${ban.map((f) => esc(f.name)).join(", ")}` : "") +
    (plus?.list_open ? ` · 알림장 목록이 '등'으로 끝나요` : "") +
    (st ? `<br><span class="stk">⭐</span> 받은 칭찬 스티커 ${st}개` : "");
  show("s-done");
  if (all && celebrate) { confetti(); say("다 챙겼지! 가방 준비 끝!"); }
}
$("#fixAlerts").addEventListener("click", () => { warnQ = openAlerts().slice(); afterWarn = () => renderDone(false); renderWarn(); });
$("#report").addEventListener("click", () => once(async () => {
  let r;                                                             // 추천·금지가 붙은 일정은 그 집계로만 보낸다(실패하면 다시 누르게)
  if (plus) { r = await api(`/api/plus/events/${ev.id}/kid-report`, { method: "POST" }); r.left = r.summary.left; }
  else r = await api(`/api/events/${ev.id}/kid-report`, { method: "POST" });
  $("#sentLead").textContent = r.left.length ? `아직 ${r.left.length}개는 엄마랑 같이 찾아보자` : "엄마가 보면 칭찬 스티커를 줄지도 몰라";
  show("s-sent");
}));
$("#again").addEventListener("click", () => once(async () => {
  for (const i of items.filter((x) => x.checked)) await setChecked(i.id, false);
  await reload();
  renderLay();
}));

/* ---------- 스티커판 ---------- */
async function openBoard() {
  backTo = onScreen() || "s-lay";
  let list = [];
  try { list = await api("/api/plus/stickers"); } catch {}
  $("#boardLead").innerHTML = list.length ? `칭찬 스티커 <b>${list.length}</b>개를 받았어` : "아직 받은 스티커가 없어";
  $("#boardGrid").innerHTML = list.map((s) => `<div class="st"><i>${esc(s.sticker)}</i><b>${esc(s.message || s.event_title)}</b><small>${esc(s.giver)} · ${esc(s.event_date.slice(5).replace("-", "/"))}</small></div>`).join("") ||
    `<div class="st empty">가방을 싸고 엄마에게 보여 주면<br>스티커를 받을 수 있어</div>`;
  show("s-board");
}
$("#openBoard").addEventListener("click", openBoard);
$("#toBoard").addEventListener("click", openBoard);
$("#boardBack").addEventListener("click", () => show(backTo));

/* ---------- 돌아오기 ---------- */
let home = null;
function renderHome() {
  const s = home.summary;
  $("#homeTitle").textContent = s.counted && !s.left.length ? "다 가져왔지! 🏠" : "집에 왔다! 가방 확인하자";
  $("#homeLead").innerHTML = !s.counted ? "다시 가져올 물건이 없어" : s.left.length ? `<b>${s.left.length}</b>개 더 찾아보자` : "두고 온 물건이 없어";
  const g = $("#homeGrid");
  g.innerHTML = home.items.map((it, i) => `<button class="card ${it.returned ? "done" : "todo"}" data-id="${it.id}" style="--tint:var(${TINTS[i % 6]})" aria-label="${esc(it.name)} ${it.returned ? "가져왔어" : "아직"}">
    ${it.tag ? `<span class="tag wear">꼬리표</span>` : ""}<span class="ic">${iconFor(it)}</span><span class="nm">${esc(it.name)}</span><span class="state">${it.returned ? "가져왔어" : "아직"}</span></button>`).join("");
  g.querySelectorAll(".card").forEach((b) => b.addEventListener("click", () => once(async () => {
    const it = home.items.find((x) => x.id == b.dataset.id);
    home = await api(`/api/plus/events/${ev.id}/return`, { method: "POST", json: { item_id: it.id, returned: !it.returned } });
    say(`${split(it.name)[0]} ${it.returned ? "아직" : "가져왔어"}`);
    renderHome();
  })));
  $("#homeReport").disabled = !s.counted;
  show("s-home");
}
$("#homeReport").addEventListener("click", () => once(async () => {
  const r = await api(`/api/plus/events/${ev.id}/return/report`, { method: "POST" });
  $("#sentLead").textContent = r.summary.left.length ? `${r.summary.left.join(", ")}은(는) 내일 학교에서 찾아보자` : "두고 온 것 없이 잘 챙겨 왔어";
  $("#again").hidden = true;                                         // 돌아오기 뒤에는 가방 싸기 체크를 푸는 버튼을 숨긴다
  show("s-sent");
}));

function confetti() {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const box = $("#confetti"), bits = ["🎉", "⭐", "🎈", "✨", "🌟"];
  for (let i = 0; i < 36; i++) {
    const s = document.createElement("span");
    s.textContent = bits[i % bits.length];
    s.style.left = Math.random() * 100 + "%";
    s.style.animationDuration = 1.8 + Math.random() * 1.6 + "s";
    s.style.animationDelay = Math.random() * 0.6 + "s";
    box.appendChild(s);
    setTimeout(() => s.remove(), 4200);
  }
}

/* ---------- 시작 ---------- */
function titleFor(e) {
  const t = e.title.replace(/^\s*\d+학년\s*/, "").replace(/\s*[(（].*?[)）]\s*/g, " ").trim();
  const d = new Date(e.date + "T00:00"), today = new Date(); today.setHours(0, 0, 0, 0);
  const gap = Math.round((d - today) / 86400000);
  const when = gap === 0 ? "오늘" : gap === 1 ? "내일" : `${d.getMonth() + 1}월 ${d.getDate()}일`;
  return `${when} ${t} 가방 싸기`;
}
(async () => {
  const q = new URLSearchParams(location.search), id = q.get("e");
  let failed = false;
  try { mode = await api("/api/plus/mode"); } catch {}
  try {
    if (id) await load(id);
    else {
      const t = new Date(); const p = (n) => String(n).padStart(2, "0");
      const list = await api(`/api/events?start=${t.getFullYear()}-${p(t.getMonth() + 1)}-${p(t.getDate())}`);
      const first = list.find((e) => e.kind !== "deadline" && e.items.length);
      if (first) await load(first.id);
    }
  } catch { failed = true; }
  if (!ev || !items.length) {
    document.querySelector("#s-lay .head").innerHTML = failed
      ? `<h1>일정을 못 불러왔어요</h1><p class="lead">잠깐 뒤에 다시 열어 봐요</p>`
      : `<h1>챙길 게 없어요</h1><p class="lead">엄마가 일정을 넣으면 여기 나와요</p>`;
    $("#layDone").disabled = true; $("#noPhoto").hidden = true; $("#photoNote").hidden = true;
    return show("s-lay");
  }
  $("#openBoard").hidden = !plus;
  $("#demoRow").hidden = !mode.demo;
  if (mode.demo) $("#photoNote").textContent = "예시 모드예요. 사진을 실제로 보지 않고 준비된 결과를 보여 줘요.";
  $("#layTitle").textContent = titleFor(ev);
  document.title = `가방쏙 · ${titleFor(ev)}`;
  if (q.get("mode") === "home" && plus) {
    home = await api(`/api/plus/events/${ev.id}/return`);
    return renderHome();
  }
  // 이미 다 넣었으면 결과부터
  required().length && required().every((i) => i.checked) ? renderDone(false) : renderLay();
})();
