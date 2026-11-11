/**
 * Everything drawn over the app in the video: captions, spotlight, pointer, badge, cards, the
 * side list and the camera zoom. Installed in every page with
 * `context.addInitScript(installOverlay, options)`.
 *
 * Lives in a shadow root on a host appended to <html>, outside <body>, so the app's CSS can't
 * restyle it and the zoom transform on <body> doesnt move it. `--font-geist-sans` still comes
 * through the shadow boundary.
 *
 * Serialised into the page: it must not use anything from the module scope.
 */
export function installOverlay(options) {
  if (window.__fmd) return;
  const W = options.width;
  const H = options.height;
  const EASE_OUT = "cubic-bezier(0.22, 1, 0.36, 1)";
  const EASE_IN = "cubic-bezier(0.55, 0, 1, 0.45)";
  const EASE_IN_OUT = "cubic-bezier(0.65, 0, 0.35, 1)";
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  // no skip link or scrollbars in the picture
  const appStyle = () => {
    const style = document.createElement("style");
    style.textContent =
      ".skip-link{display:none!important}" +
      "html{scrollbar-width:none}*{scrollbar-width:none}*::-webkit-scrollbar{display:none}";
    (document.head || document.documentElement).appendChild(style);
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", appStyle, { once: true });
  else appStyle();

  const CSS = `
    :host { all: initial; }
    * { box-sizing: border-box; }
    .layer { position: fixed; inset: 0; pointer-events: none; font-family: var(--font-geist-sans), ui-sans-serif, system-ui, sans-serif;
      color: ${options.colors.text}; -webkit-font-smoothing: antialiased; font-feature-settings: "tnum" 1; }
    .ring { position: absolute; border-radius: 12px; opacity: 0;
      box-shadow: 0 0 0 2px ${options.colors.accent}, 0 0 24px 2px ${options.colors.accent}55, 0 0 0 9999px rgba(5, 5, 5, 0.52);
      transition: left 380ms ${EASE_OUT}, top 380ms ${EASE_OUT}, width 380ms ${EASE_OUT}, height 380ms ${EASE_OUT}, opacity 260ms ${EASE_OUT}; }
    .callout { position: absolute; max-width: 460px; padding: 10px 16px; border-radius: 10px; opacity: 0;
      background: ${options.colors.accentSolid}; color: #fff; font-size: 20px; font-weight: 600; line-height: 1.3;
      box-shadow: 0 8px 28px rgba(0, 0, 0, 0.45); transform: translateY(8px);
      transition: opacity 240ms ${EASE_OUT}, transform 240ms ${EASE_OUT}; }
    .callout.on { opacity: 1; transform: none; }
    .caption { position: absolute; left: 50%; transform: translateX(-50%); bottom: 44px; max-width: 1080px; width: max-content;
      padding: 12px 22px; border-radius: 12px; background: rgba(10, 10, 10, 0.86); border: 1px solid rgba(255, 255, 255, 0.08);
      font-size: 27px; line-height: 1.38; font-weight: 500; text-align: center; opacity: 0; transition: opacity 180ms ${EASE_OUT}; }
    .caption.top { bottom: auto; top: 44px; }
    .caption.on { opacity: 1; }
    .caption span { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
    .badge { position: absolute; top: 18px; right: 18px; display: flex; align-items: center; gap: 8px; padding: 7px 14px;
      border-radius: 999px; background: rgba(10, 10, 10, 0.86); border: 1px solid ${options.colors.warn}; color: ${options.colors.warn};
      font-size: 17px; font-weight: 600; opacity: 0; transition: opacity 160ms ${EASE_OUT}; }
    .badge.on { opacity: 1; }
    .pointer { position: absolute; left: 0; top: 0; width: 30px; height: 30px; opacity: 0; transition: opacity 200ms ${EASE_OUT};
      filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.6)); will-change: transform; }
    .pointer.on { opacity: 1; }
    .tick { position: absolute; right: 0; bottom: 0; width: 2px; height: 2px; background: #000; opacity: 0.011; }
    .ripple { position: absolute; width: 56px; height: 56px; margin: -28px 0 0 -28px; border-radius: 50%;
      border: 3px solid ${options.colors.accent}; background: ${options.colors.accent}33; }
    .card { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; opacity: 0;
      background: radial-gradient(1200px 700px at 70% 20%, ${options.colors.accent}26, transparent 60%),
                  radial-gradient(900px 600px at 10% 90%, ${options.colors.accentSolid}1f, transparent 60%), ${options.colors.bg};
      transition: opacity 320ms ${EASE_OUT}; }
    .card.on { opacity: 1; }
    .card.off { opacity: 0; transition: opacity 260ms ${EASE_IN}; }
    .card .grid { position: absolute; inset: 0; opacity: 0.35;
      background-image: linear-gradient(${options.colors.border} 1px, transparent 1px), linear-gradient(90deg, ${options.colors.border} 1px, transparent 1px);
      background-size: 64px 64px; mask-image: radial-gradient(closest-side, black, transparent); -webkit-mask-image: radial-gradient(closest-side, black, transparent); }
    .card .inner { position: relative; max-width: 1180px; padding: 0 72px; }
    .card .item { opacity: 0; transform: translateY(16px); }
    .card .item.in { opacity: 1; transform: none; transition: opacity 520ms ${EASE_OUT}, transform 520ms ${EASE_OUT}; }
    .eyebrow { font-size: 18px; font-weight: 600; letter-spacing: 0.14em; text-transform: uppercase; color: ${options.colors.accentText}; margin-bottom: 18px; }
    .wordmark { display: flex; align-items: center; gap: 18px; margin-bottom: 26px; }
    .wordmark svg { width: 64px; height: 64px; }
    .wordmark span { font-size: 40px; font-weight: 600; letter-spacing: -0.01em; }
    .wordmark em { font-style: normal; color: ${options.colors.accentText}; }
    .title { font-size: 68px; font-weight: 650; letter-spacing: -0.02em; line-height: 1.06; margin: 0 0 22px; }
    .subtitle { font-size: 28px; line-height: 1.4; color: ${options.colors.textMuted}; margin: 0 0 30px; max-width: 980px; }
    .chips { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 30px; }
    .chip { padding: 9px 16px; border-radius: 999px; border: 1px solid ${options.colors.border}; background: ${options.colors.surface};
      font-size: 20px; font-weight: 500; }
    .cta { display: inline-flex; align-items: center; gap: 12px; padding: 14px 22px; border-radius: 10px; background: ${options.colors.accentSolid};
      color: #fff; font-size: 24px; font-weight: 600; margin-bottom: 26px; }
    .footnote { font-size: 17px; line-height: 1.5; color: ${options.colors.textMuted}; max-width: 980px; }
    .list { position: absolute; top: 50%; width: 470px; padding: 26px 28px; border-radius: 16px; opacity: 0;
      background: rgba(10, 10, 10, 0.88); border: 1px solid ${options.colors.border}; box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
      transform: translateY(-50%) translateX(12px); transition: opacity 300ms ${EASE_OUT}, transform 300ms ${EASE_OUT}; }
    .list.right { right: 380px; } .list.left { left: 380px; }
    .list.center { left: 50%; transform: translate(-50%, -50%) translateY(12px); }
    .list.center.on { transform: translate(-50%, -50%); }
    .list.on { opacity: 1; transform: translateY(-50%); }
    .list h2 { margin: 0 0 18px; font-size: 18px; font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase; color: ${options.colors.accentText}; }
    .list ol { margin: 0; padding: 0; list-style: none; display: grid; gap: 14px; }
    .list li { display: flex; align-items: center; gap: 14px; font-size: 25px; font-weight: 500; opacity: 0; transform: translateY(10px); }
    .list li.in { opacity: 1; transform: none; transition: opacity 420ms ${EASE_OUT}, transform 420ms ${EASE_OUT}; }
    .list li b { flex: none; display: grid; place-items: center; width: 34px; height: 34px; border-radius: 50%;
      background: ${options.colors.accent}26; color: ${options.colors.accentText}; font-size: 17px; }
  `;

  const POINTER_SVG =
    '<svg viewBox="0 0 24 24" width="30" height="30" aria-hidden="true"><path d="M4 2.5 L4 19.5 L8.6 15.4 L11.6 21.6 L14.6 20.2 L11.7 14.1 L17.8 14.1 Z" fill="#fff" stroke="#0a0a0a" stroke-width="1.4" stroke-linejoin="round"/></svg>';
  const FAST_SVG =
    '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path d="M3 5 L11 12 L3 19 Z M12 5 L20 12 L12 19 Z" fill="currentColor"/></svg>';
  // the app header's mark (frontend/app/layout.tsx): lucide's Activity trace
  const MARK_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="${options.colors.accent}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>`;

  let shadow = null;
  const el = {};
  const pointer = { x: W * 0.62, y: H * 0.58, shown: false };

  function root() {
    if (shadow) return shadow;
    const host = document.createElement("div");
    host.id = "fmd-video-overlay";
    host.style.cssText = "position:fixed;inset:0;pointer-events:none;z-index:2147483647;";
    document.documentElement.appendChild(host);
    shadow = host.attachShadow({ mode: "open" });
    shadow.innerHTML = `<style>${CSS}</style><div class="layer">
      <div class="ring"></div><div class="callout"></div>
      <div class="list right"></div>
      <div class="card"></div>
      <div class="caption"><span></span></div>
      <div class="badge">${FAST_SVG}<span></span></div>
      <div class="ripples"></div>
      <div class="pointer">${POINTER_SVG}</div>
      <div class="tick"></div></div>`;
    for (const name of ["ring", "callout", "list", "card", "caption", "badge", "ripples", "pointer", "tick"]) {
      el[name] = shadow.querySelector(`.${name}`);
    }
    el.captionText = el.caption.querySelector("span");
    el.badgeText = el.badge.querySelector("span");
    placePointer();
    return shadow;
  }

  function placePointer() {
    el.pointer.style.transform = `translate(${pointer.x - 4}px, ${pointer.y - 2}px)`;
  }

  let captionPlacement = "bottom";
  function caption(text) {
    root();
    if (!text) {
      el.caption.classList.remove("on");
      return;
    }
    el.caption.classList.toggle("top", captionPlacement === "top");
    if (el.captionText.textContent !== text) {
      el.captionText.textContent = text;
      el.caption.animate([{ opacity: 0.25 }, { opacity: 1 }], { duration: 180, easing: EASE_OUT });
    }
    el.caption.classList.add("on");
  }
  function setCaptionPlacement(placement) {
    root();
    if (placement === captionPlacement) return;
    captionPlacement = placement;
    el.caption.classList.toggle("top", placement === "top");
  }

  function spotlight(rect, label) {
    root();
    const pad = 10;
    const box = {
      x: Math.max(4, rect.x - pad),
      y: Math.max(4, rect.y - pad),
      w: Math.min(W - 8, rect.width + 2 * pad),
      h: Math.min(H - 8, rect.height + 2 * pad),
    };
    const ring = el.ring;
    const first = ring.style.opacity !== "1";
    if (first) ring.style.transition = "none";
    ring.style.left = `${box.x}px`;
    ring.style.top = `${box.y}px`;
    ring.style.width = `${box.w}px`;
    ring.style.height = `${box.h}px`;
    if (first) {
      void ring.offsetWidth; // apply the position before fading in
      ring.style.transition = "";
    }
    ring.style.opacity = "1";
    // Captions go to the half of the screen the spotlight is not in.
    setCaptionPlacement(box.y + box.h / 2 > H * 0.55 ? "top" : "bottom");

    const callout = el.callout;
    callout.classList.remove("on");
    if (!label) return;
    callout.textContent = label;
    callout.style.left = "0px";
    callout.style.top = "0px";
    const size = callout.getBoundingClientRect();
    const below = box.y + box.h + 14;
    const above = box.y - 14 - size.height;
    let top;
    if (below + size.height <= H - 110) top = below;
    else if (above >= 90) top = above;
    else top = box.y + 14; // tall target: inside its top edge
    const left = Math.min(W - 16 - size.width, Math.max(16, box.x + box.w / 2 - size.width / 2));
    callout.style.left = `${left}px`;
    callout.style.top = `${top}px`;
    setTimeout(() => callout.classList.add("on"), 140);
  }
  function clearSpotlight() {
    root();
    el.ring.style.opacity = "0";
    el.callout.classList.remove("on");
    setCaptionPlacement("bottom");
  }

  function pointerTo(x, y, durationMs) {
    root();
    if (!pointer.shown) {
      pointer.shown = true;
      el.pointer.classList.add("on");
    }
    const from = { x: pointer.x, y: pointer.y };
    const distance = Math.hypot(x - from.x, y - from.y);
    const duration = durationMs ?? Math.min(900, Math.max(320, 260 + distance * 0.55));
    return new Promise((resolve) => {
      const start = performance.now();
      const step = (now) => {
        const p = Math.min(1, (now - start) / duration);
        const e = p < 0.5 ? 4 * p * p * p : 1 - (-2 * p + 2) ** 3 / 2; // easeInOutCubic
        pointer.x = from.x + (x - from.x) * e;
        pointer.y = from.y + (y - from.y) * e;
        placePointer();
        if (p < 1) requestAnimationFrame(step);
        else resolve(duration);
      };
      requestAnimationFrame(step);
    });
  }
  function hidePointer() {
    root();
    pointer.shown = false;
    el.pointer.classList.remove("on");
  }
  function ripple(x, y) {
    root();
    const dot = document.createElement("div");
    dot.className = "ripple";
    dot.style.left = `${x}px`;
    dot.style.top = `${y}px`;
    el.ripples.appendChild(dot);
    const anim = dot.animate(
      [
        { transform: "scale(0.25)", opacity: 0.85 },
        { transform: "scale(1)", opacity: 0 },
      ],
      { duration: 480, easing: EASE_OUT },
    );
    anim.onfinish = () => dot.remove();
    el.pointer.animate([{ transform: el.pointer.style.transform + " scale(1)" }, { transform: el.pointer.style.transform + " scale(0.86)" }, { transform: el.pointer.style.transform + " scale(1)" }], {
      duration: 200,
      easing: EASE_IN_OUT,
    });
  }

  function badge(text) {
    root();
    if (text) el.badgeText.textContent = text;
    el.badge.classList.toggle("on", Boolean(text));
  }

  const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  async function card(spec) {
    root();
    const parts = ['<div class="grid"></div><div class="inner">'];
    if (spec.wordmark) {
      const text = spec.wordmark === "FlightMD" ? "Flight<em>MD</em>" : escapeHtml(spec.wordmark);
      parts.push(`<div class="item wordmark">${MARK_SVG}<span>${text}</span></div>`);
    }
    if (spec.eyebrow) parts.push(`<div class="item eyebrow">${escapeHtml(spec.eyebrow)}</div>`);
    if (spec.title) parts.push(`<h1 class="item title">${escapeHtml(spec.title)}</h1>`);
    if (spec.subtitle) parts.push(`<p class="item subtitle">${escapeHtml(spec.subtitle)}</p>`);
    if (spec.chips?.length) parts.push(`<div class="item chips">${spec.chips.map((c) => `<span class="chip">${escapeHtml(c)}</span>`).join("")}</div>`);
    if (spec.cta) parts.push(`<div class="item cta">${escapeHtml(spec.cta)}</div>`);
    if (spec.footnote) parts.push(`<p class="item footnote">${escapeHtml(spec.footnote)}</p>`);
    parts.push("</div>");
    el.card.innerHTML = parts.join("");
    el.card.classList.remove("off");
    el.card.classList.add("on");
    const items = [...el.card.querySelectorAll(".item")];
    const stagger = spec.staggerMs ?? 90;
    await wait(120);
    items.forEach((item, i) => setTimeout(() => item.classList.add("in"), i * stagger));
    await wait(items.length * stagger + 520);
  }
  async function closeCard() {
    root();
    el.card.classList.add("off");
    el.card.classList.remove("on");
    await wait(280);
  }

  async function list(spec) {
    root();
    el.list.className = `list ${["left", "center"].includes(spec.side) ? spec.side : "right"}`;
    el.list.innerHTML =
      (spec.title ? `<h2>${escapeHtml(spec.title)}</h2>` : "") +
      `<ol>${spec.items.map((item, i) => `<li><b>${i + 1}</b><span>${escapeHtml(item)}</span></li>`).join("")}</ol>`;
    void el.list.offsetWidth;
    el.list.classList.add("on");
    const rows = [...el.list.querySelectorAll("li")];
    const stagger = spec.staggerMs ?? 450;
    await wait(spec.delayMs ?? 250);
    for (const row of rows) {
      row.classList.add("in");
      await wait(stagger);
    }
  }
  function closeList() {
    root();
    el.list.classList.remove("on");
  }

  async function zoom(rect, maxScale) {
    root();
    const scale = Math.max(1, Math.min(maxScale, (0.72 * W) / rect.width, (0.72 * H) / rect.height));
    if (scale < 1.08) return 1;
    const cx = rect.x + rect.width / 2;
    const cy = rect.y + rect.height / 2;
    // Origin P such that P + s(C - P) = viewport centre, clamped so no edge of the page shows.
    const ox = Math.min(W, Math.max(0, (scale * cx - W / 2) / (scale - 1)));
    const oy = Math.min(H, Math.max(0, (scale * cy - H / 2) / (scale - 1)));
    document.documentElement.style.overflow = "hidden";
    const body = document.body;
    body.style.transformOrigin = `${ox}px ${oy}px`;
    body.style.transition = `transform 760ms ${EASE_OUT}`;
    body.style.transform = `scale(${scale})`;
    await wait(800);
    return scale;
  }
  async function zoomOut() {
    root();
    const body = document.body;
    if (!body.style.transform || body.style.transform === "none") return;
    body.style.transition = `transform 640ms ${EASE_IN_OUT}`;
    body.style.transform = "none";
    await wait(680);
    body.style.transition = "";
  }

  // Forces a repaint without a visible change (see ScreencastRecorder.drain).
  let tickState = false;
  function tick() {
    root();
    tickState = !tickState;
    el.tick.style.opacity = tickState ? "0.012" : "0.011";
  }

  window.__fmd = {
    tick,
    caption,
    spotlight,
    clearSpotlight,
    pointerTo,
    hidePointer,
    ripple,
    badge,
    card,
    closeCard,
    list,
    closeList,
    zoom,
    zoomOut,
  };
}
