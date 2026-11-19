/* 가방쏙 예시 판(서버 없이 브라우저 안에서 도는 판)의 연결 고리.
   화면 코드는 서버 판과 같다. /api/ 요청만 바깥 틀(프로토타입 페이지)이 가진 계산 코드로 보낸다.
   사진 파일은 개수만 세고 내용은 넘기지 않는다(예시 판은 사진을 보지 않는다). */
(() => {
  let host = null;
  try { host = window.parent !== window && window.parent.chaengApi ? window.parent : null; } catch { host = null; }
  if (!host) {                                   // 틀 밖에서 바로 열면 프로토타입 첫 화면으로
    location.replace("../index.html");
    return;
  }
  const realFetch = window.fetch.bind(window);
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  window.fetch = async (input, opt = {}) => {
    const url = typeof input === "string" ? input : input.url;
    if (!url.startsWith("/api/")) return realFetch(input, opt);
    let json = "", fields = "", files = 0;
    const b = opt.body;
    if (typeof b === "string") json = b;
    else if (b instanceof FormData) {
      const f = {};
      for (const [k, v] of b.entries()) { if (typeof v === "string") f[k] = v; else files++; }
      fields = JSON.stringify(f);
    }
    await wait(/photo-check|notice\/extract/.test(url) ? 900 : 40);   // 읽는 중 화면이 잠깐 보이게
    let status = 500, body = { detail: "예시 판 계산 코드를 부르지 못했어요" };
    try { [status, body] = host.chaengApi((opt.method || "GET").toUpperCase(), url, json, fields, files); } catch (e) { console.error(e); }
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  };
  document.addEventListener("click", (e) => {     // 아이 화면·엄마 화면 사이의 이동은 바깥 틀이 맡는다
    const a = e.target.closest && e.target.closest("a[href]");
    if (a && host.chaengLink && host.chaengLink(a.getAttribute("href"), window.name)) e.preventDefault();
  }, true);
})();
