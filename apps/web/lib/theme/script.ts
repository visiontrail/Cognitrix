export const THEME_STORAGE_KEY = "cognitrix.theme";

export type ThemeMode = "light" | "dark";
export type ResolvedTheme = "light" | "dark";

export const THEME_MODES: ThemeMode[] = ["light", "dark"];

export function isThemeMode(value: string | null): value is ThemeMode {
  return value === "light" || value === "dark";
}

export function themeBootstrapScript(): string {
  return `
(function () {
  try {
    var stored = window.localStorage.getItem("${THEME_STORAGE_KEY}");
    var mode = stored === "light" || stored === "dark" ? stored : "light";
    var root = document.documentElement;
    root.classList.toggle("dark", mode === "dark");
    root.dataset.theme = mode;
    root.dataset.themeMode = mode;
    root.style.colorScheme = mode;
  } catch (error) {
    document.documentElement.dataset.theme = "light";
    document.documentElement.dataset.themeMode = "light";
    document.documentElement.style.colorScheme = "light";
  }
})();
`.trim();
}
