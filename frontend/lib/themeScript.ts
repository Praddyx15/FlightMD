// No "use client": the root layout (a server component) inlines this.

export const THEME_KEY = "flightmd.theme";
export const THEME_EVENT = "flightmd-theme";

// Runs inline in <head> before first paint so the page never flashes the wrong theme.
// Kept as a string because it has to work before React loads.
export const themeInitScript = `(function(){try{var t=localStorage.getItem("${THEME_KEY}");if(t!=="light"&&t!=="dark"){t=window.matchMedia("(prefers-color-scheme: light)").matches?"light":"dark"}if(t==="light")document.documentElement.classList.add("light")}catch(e){}})();`;
