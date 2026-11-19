/* 아이 미션: 펼치기(C-1) → 사진/하나씩 확인(C-2) → 결과(C-3) → 엄마에게 보여 주기
   원칙: 누르는 칸은 크게, 한 화면에 할 일 하나, '다시 빼기'는 눈에 보이게, 다 넣기 전엔 칭찬 없음. */
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const TINTS = ["--t1", "--t2", "--t3", "--t4", "--t5", "--t6"];

// 준비물 이름 → 그림. 위에서부터 먼저 맞는 것.
const ICONS = [
  [/도시락|밥/, "🍱"], [/수저|젓가락|숟가락/, "🥢"], [/간식|과자/, "🍪"], [/과일/, "🍎"],
  [/물티슈|휴지|티슈/, "🧻"], [/물통|텀블러/, "🥤"], [/물|음료|생수/, "💧"],
  [/돗자리|매트/, "🧺"], [/모자/, "🧢"], [/손수건|수건/, "🧣"],
  [/우산/, "☂️"], [/우비|비옷/, "🧥"], [/마스크/, "😷"], [/장갑|핫팩/, "🧤"], [/양말/, "🧦"],
  [/반티|티셔츠|체육복|옷/, "👕"], [/실내화|운동화|신발/, "👟"], [/공연복|한복|드레스/, "👗"],
  [/보조가방|가방|봉투|비닐/, "🛍️"], [/교재|책|교과서|공책|노트/, "📚"], [/필기|연필|펜|필통/, "✏️"],
  [/색연필|크레파스|사인펜/, "🖍️"], [/가위/, "✂️"], [/풀/, "🧴"], [/자$|자\b/, "📏"],
  [/멀미|약/, "💊"], [/선크림|썬크림/, "🧴"], [/신청서|회신|동의서|서류/, "📝"],
  [/줄넘기/, "🪢"], [/카메라/, "📷"], [/이름표|명찰/, "🏷️"], [/돈|용돈|카드/, "🪙"], [/안경/, "👓"],
];
const iconFor = (n) => (ICONS.find(([re]) => re.test(n)) || [, "🎒"])[1];

// "물(음료)" → 큰 글씨 "물", 작은 글씨 "음료"
function split(name) {
  const m = name.match(/^(.*?)\s*[(（](.+?)[)）]\s*$/);
  return m ? [m[1], m[2]] : [name, ""];
}
// 날씨 준비물은 아이가 이해할 말로
function kidHint(it) {
  if (it.source !== "weather") return split(it.name)[1];
  if (/우산|우비/.test(it.name)) return "비 소식이 있대요";
  if (/마스크/.test(it.name)) return "먼지가 많대요";
  if (/장갑|핫팩|겉옷/.test(it.name)) return "추운 날이에요";
  if (/모자|물/.test(it.name)) return "더운 날이에요";
  return "";
}

let ev = null, queue = [], qi = 0, fromPhoto = false;

async function api(path, opt = {}) {
  const r = await fetch(path, opt.json ? { ...opt, headers: { "Content-Type": "application/json" }, body: JSON.stringify(opt.json) } : opt);
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch {} throw new Error(m); }
  return r.json();
}
function toast(m, ms = 2600) {
  const t = $("#toast"); t.textContent = m; t.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => (t.hidden = true), ms);
}
function show(id) {
  document.querySelectorAll(".screen").forEach((s) => s.classList.toggle("on", s.id === id));
  window.scrollTo(0, 0);
}

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
  const on = document.querySelector(".screen.on")?.id;
  if (on === "s-one" && queue[qi]) return say(`${split(queue[qi].name)[0]}. 가방에 넣었으면 넣었어 버튼을 눌러요.`);
  if (on === "s-done") return say($("#doneTitle").textContent + ". " + $("#doneLead").textContent);
  say(`${$("#layTitle").textContent}. ${ev.items.map((i) => split(i.name)[0]).join(", ")}. 모두 ${ev.items.length}개를 펼쳐 놓자.`);
});

/* ---------- 카드 ---------- */
function card(it, i, mode) {
  const [nm] = split(it.name), hint = kidHint(it);
  const cls = mode === "result" ? (it.checked ? "done" : "todo") : "";
  const state = mode === "result" ? `<span class="state">${it.checked ? "넣었음" : "아직"}</span>` : "";
  return `<button class="card ${cls}" data-id="${it.id}" style="--tint:var(${TINTS[i % 6]})" aria-label="${esc(nm)}${mode === "result" ? (it.checked ? " 넣었음" : " 아직") : ""}">
    <span class="ic">${iconFor(it.name)}</span><span class="nm">${esc(nm)}</span>${hint && mode !== "result" ? `<span class="hint">${esc(hint)}</span>` : ""}${state}</button>`;
}

/* ---------- C-1 펼치기 ---------- */
function renderLay() {
  const g = $("#layGrid");
  g.innerHTML = ev.items.map((it, i) => card(it, i, "lay")).join("");
  g.querySelectorAll(".card").forEach((b) => b.addEventListener("click", () => {
    const it = ev.items.find((x) => x.id == b.dataset.id);
    b.classList.remove("pop"); void b.offsetWidth; b.classList.add("pop");
    say(split(it.name)[0]);
  }));
  $("#layCount").textContent = ev.items.length;
  show("s-lay");
}
$("#layDone").addEventListener("click", () => $("#photo").click());
$("#noPhoto").addEventListener("click", () => startOne(ev.items.filter((i) => !i.checked), false));
$("#photo").addEventListener("change", async (e) => {
  const f = e.target.files[0]; e.target.value = "";
  if (!f) return;
  $("#scanImg").src = URL.createObjectURL(f);
  show("s-scan");
  try {
    const fd = new FormData(); fd.append("image", f);
    const r = await api(`/api/events/${ev.id}/photo-check`, { method: "POST", body: fd });
    await Promise.all(r.seen.map((id) => setChecked(id, true)));
    startOne(ev.items.filter((i) => r.not_seen.includes(i.id) && !i.checked), true);
  } catch (err) {
    toast("사진을 못 봤어요. 하나씩 같이 볼까요?");
    startOne(ev.items.filter((i) => !i.checked), false);
  }
});

async function setChecked(id, v) {
  const it = ev.items.find((x) => x.id === id);
  if (it) it.checked = v;
  await api(`/api/items/${id}`, { method: "PATCH", json: { checked: v } });
}

/* ---------- C-2 하나씩 ---------- */
function startOne(list, photo) {
  queue = list; qi = 0; fromPhoto = photo;
  if (!queue.length) return renderDone();
  show("s-one");
  renderOne();
}
function renderOne() {
  const it = queue[qi], left = queue.length - qi;
  $("#oneTitle").textContent = left === 1 ? "하나만 더 보자" : `${left}개 더 보자`;
  $("#oneLead").textContent = fromPhoto ? "사진에서 안 보였어" : "하나씩 가방에 넣어 보자";
  // 점: 이미 넣은 것(채움) · 지금(굵은 테두리) · 남은 것(점선)
  $("#dots").innerHTML = ev.items.map((x, i) =>
    `<i class="${x.checked ? "" : x.id === it.id ? "now" : "left"}"></i>`).join("");
  const [nm] = split(it.name), hint = kidHint(it);
  const big = $("#bigCard");
  big.className = "big in";
  big.innerHTML = `<span class="ic">${iconFor(it.name)}</span><span class="nm">${esc(nm)}</span>${hint ? `<span class="hint">${esc(hint)}</span>` : ""}`;
  big.setAttribute("aria-label", nm);
  $("#bagIcon").classList.remove("show");
  $("#putIn").disabled = false;
  say(nm);
}
$("#bigCard").addEventListener("click", () => say(split(queue[qi].name)[0]));
$("#putIn").addEventListener("click", async () => {
  $("#putIn").disabled = true;
  $("#bagIcon").classList.add("show");
  $("#bigCard").classList.replace("in", "drop");
  navigator.vibrate?.(30);
  await setChecked(queue[qi].id, true);
  setTimeout(next, 700);
});
$("#notYet").addEventListener("click", () => {
  $("#bigCard").classList.replace("in", "skip");
  setTimeout(next, 350);
});
function next() { qi++; qi < queue.length ? renderOne() : renderDone(); }

/* ---------- C-3 결과 ---------- */
function renderDone(celebrate = true) {
  const done = ev.items.filter((i) => i.checked), left = ev.items.filter((i) => !i.checked);
  const all = left.length === 0;
  $("#s-done").classList.toggle("allclear", all);
  $("#doneTitle").textContent = all ? "다 챙겼지! 🎉" : `${done.length}개 넣었어!`;
  $("#doneLead").innerHTML = all ? "가방 준비 끝!" : `<b>${left.length}</b>개 남았어`;
  const g = $("#doneGrid");
  g.innerHTML = ev.items.map((it, i) => card(it, i, "result")).join("");
  g.querySelectorAll(".card").forEach((b) => b.addEventListener("click", async () => {
    const it = ev.items.find((x) => x.id == b.dataset.id);
    await setChecked(it.id, !it.checked);
    say(it.checked ? `${split(it.name)[0]} 넣었음` : `${split(it.name)[0]} 다시 뺐어`);
    renderDone(false);
  }));
  $("#parentNote").innerHTML = `<b>엄마에게:</b> 준비물 ${ev.items.length} · 넣음 ${done.length} · 아직 ${left.length}` +
    (left.length ? ` (${left.map((i) => esc(split(i.name)[0])).join(", ")})` : "");
  show("s-done");
  if (all && celebrate) { confetti(); say("다 챙겼지! 가방 준비 끝!"); }
}
$("#report").addEventListener("click", async () => {
  $("#report").disabled = true;
  try {
    const r = await api(`/api/events/${ev.id}/kid-report`, { method: "POST" });
    $("#sentLead").textContent = r.left.length ? `아직 ${r.left.length}개는 엄마랑 같이 찾아보자` : "엄마가 확인할 거야";
    show("s-sent");
  } catch (e) { toast("못 보냈어요. 다시 눌러 줘요"); }
  $("#report").disabled = false;
});
$("#again").addEventListener("click", async () => {
  await Promise.all(ev.items.filter((i) => i.checked).map((i) => setChecked(i.id, false)));
  renderLay();
});

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
  const id = new URLSearchParams(location.search).get("e");
  try {
    if (id) ev = await api(`/api/events/${id}`);
    else {
      const t = new Date(); const p = (n) => String(n).padStart(2, "0");
      const list = await api(`/api/events?start=${t.getFullYear()}-${p(t.getMonth() + 1)}-${p(t.getDate())}`);
      ev = list.find((e) => e.kind !== "deadline" && e.items.length);
    }
  } catch {}
  if (!ev || !ev.items.length) {
    document.querySelector("#s-lay .head").innerHTML = `<h1>챙길 게 없어요</h1><p class="lead">엄마가 일정을 넣으면 여기 나와요</p>`;
    $("#layDone").disabled = true; $("#noPhoto").hidden = true;
    return show("s-lay");
  }
  $("#layTitle").textContent = titleFor(ev);
  document.title = `챙겼지 · ${titleFor(ev)}`;
  // 이미 다 넣었으면 결과부터
  ev.items.every((i) => i.checked) ? renderDone(false) : renderLay();
})();
