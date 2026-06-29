"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  THEME_MODES,
  THEME_STORAGE_KEY,
  isThemeMode,
  type ResolvedTheme,
  type ThemeMode,
} from "./script";

type ThemeContextValue = {
  mode: ThemeMode;
  resolvedTheme: ResolvedTheme;
  setMode: (mode: ThemeMode) => void;
};

function resolveStoredThemeMode(): ThemeMode {
  if (typeof window === "undefined") {
    return "light";
  }
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isThemeMode(stored) ? stored : "light";
  } catch {
    return "light";
  }
}

function applyTheme(mode: ThemeMode, resolvedTheme: ResolvedTheme) {
  if (typeof document === "undefined") {
    return;
  }
  const root = document.documentElement;
  root.classList.toggle("dark", resolvedTheme === "dark");
  root.dataset.theme = resolvedTheme;
  root.dataset.themeMode = mode;
  root.style.colorScheme = resolvedTheme;
}

const defaultThemeContext: ThemeContextValue = {
  mode: "light",
  resolvedTheme: "light",
  setMode: () => {
    // no-op fallback for isolated renders
  },
};

const ThemeContext = createContext<ThemeContextValue>(defaultThemeContext);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>("light");
  const [resolvedTheme, setResolvedTheme] = useState<ResolvedTheme>("light");

  useEffect(() => {
    const initialMode = resolveStoredThemeMode();
    setModeState(initialMode);
    setResolvedTheme(initialMode);
    applyTheme(initialMode, initialMode);
  }, []);

  const setMode = useCallback((nextMode: ThemeMode) => {
    if (!THEME_MODES.includes(nextMode)) {
      return;
    }
    setModeState(nextMode);
    setResolvedTheme(nextMode);
    applyTheme(nextMode, nextMode);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, nextMode);
    } catch {
      // Ignore storage denial; the in-memory theme still updates.
    }
  }, []);

  const value = useMemo<ThemeContextValue>(
    () => ({ mode, resolvedTheme, setMode }),
    [mode, resolvedTheme, setMode]
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  return useContext(ThemeContext);
}

export type { ThemeMode, ResolvedTheme };
