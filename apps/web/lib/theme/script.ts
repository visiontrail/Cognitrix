export const THEME_STORAGE_KEY = "cognitrix.theme";

export type ThemeMode = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

export const THEME_MODES: ThemeMode[] = ["system", "light", "dark"];

export function isThemeMode(value: string | null): value is ThemeMode {
  return value === "system" || value === "light" || value === "dark";
}

export function themeBootstrapScript(): string {
  return `
(function () {
  try {
    var stored = window.localStorage.getItem("${THEME_STORAGE_KEY}");
    var mode = stored === "light" || stored === "dark" || stored === "system" ? stored : "system";
    var prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    var resolved = mode === "system" ? (prefersDark ? "dark" : "light") : mode;
    var root = document.documentElement;
    root.classList.toggle("dark", resolved === "dark");
    root.dataset.theme = resolved;
    root.dataset.themeMode = mode;
    root.style.colorScheme = resolved;
  } catch (error) {
    document.documentElement.dataset.themeMode = "system";
  }
})();
`.trim();
}
