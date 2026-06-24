"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Globe } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiEmailLogin, AuthError } from "@/lib/auth/auth-client";
import { setInMemoryToken, setStoredAppMode } from "@/lib/auth/session";
import { useI18n } from "@/lib/i18n/context";
import { SUPPORTED_LOCALES, type Locale } from "@/lib/i18n/dictionary";

const LOCALE_LABELS: Record<Locale, string> = {
  "en-US": "English",
  "zh-CN": "中文",
};

function LanguageSwitcher() {
  const { locale, setLocale, t } = useI18n();

  return (
    <div className="absolute top-5 right-5 flex items-center gap-1">
      <Globe className="h-4 w-4 text-olive-gray" />
      {SUPPORTED_LOCALES.map((loc, i) => (
        <span key={loc} className="flex items-center">
          {i > 0 && <span className="text-stone-gray mx-1">/</span>}
          <button
            type="button"
            onClick={() => setLocale(loc)}
            className={`text-body-sm transition-colors ${
              locale === loc
                ? "text-near-black font-medium"
                : "text-stone-gray hover:text-olive-gray"
            }`}
          >
            {LOCALE_LABELS[loc]}
          </button>
        </span>
      ))}
    </div>
  );
}

function LoginForm() {
  const searchParams = useSearchParams();
  const next = searchParams.get("next") ?? "/";
  const invite = searchParams.get("invite");
  const { t } = useI18n();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const result = await apiEmailLogin({ email, password });
      setInMemoryToken(result.access_token, result.expires_at);
      setStoredAppMode("designer");
      window.location.href = invite ? `/invites/${invite}` : next;
    } catch (err) {
      setLoading(false);
      setError(err instanceof AuthError ? t("auth.loginError") : t("auth.loginFailed"));
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLFormElement>) {
    if (e.key === "Enter" && !e.nativeEvent.isComposing && !loading) {
      e.preventDefault();
      e.currentTarget.requestSubmit();
    }
  }

  return (
    <form onSubmit={handleSubmit} onKeyDown={handleKeyDown} className="space-y-5">
      <div className="space-y-1.5">
        <label htmlFor="email" className="block text-label font-medium text-charcoal-warm tracking-wide uppercase">
          {t("auth.emailAddress")}
        </label>
        <Input
          id="email"
          type="email"
          autoComplete="email"
          placeholder="you@example.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <label htmlFor="password" className="block text-label font-medium text-charcoal-warm tracking-wide uppercase">
            {t("auth.password")}
          </label>
        </div>
        <Input
          id="password"
          type="password"
          autoComplete="current-password"
          placeholder="••••••••"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
      </div>

      {error && (
        <div className="rounded-comfortable border border-error-crimson/20 bg-error-crimson/5 px-4 py-3">
          <p className="text-body-sm text-error-crimson">{error}</p>
        </div>
      )}

      <Button
        type="submit"
        className="w-full h-10 text-body font-medium"
        disabled={loading}
      >
        {loading ? (
          <span className="flex items-center gap-2">
            <span className="h-4 w-4 rounded-full border-2 border-ivory/30 border-t-ivory animate-spin" />
            {t("auth.loggingIn")}
          </span>
        ) : (
          t("auth.login")
        )}
      </Button>
    </form>
  );
}

export default function LoginPage() {
  const { t } = useI18n();

  return (
    <div className="relative min-h-screen bg-parchment flex flex-col items-center justify-center p-6">
      <LanguageSwitcher />

      {/* Brand */}
      <div className="mb-10 text-center">
        <div className="inline-flex items-baseline gap-2 mb-3">
          <span className="font-serif text-[1.6rem] font-[500] leading-none text-near-black">Cognitrix</span>
        </div>
        <h1 className="font-serif text-heading text-near-black">{t("auth.welcomeBack")}</h1>
        <p className="mt-2 text-olive-gray text-body">{t("auth.loginSubtitle")}</p>
      </div>

      {/* Card */}
      <div className="w-full max-w-sm bg-ivory rounded-very border border-border-cream shadow-whisper px-8 py-9">
        <Suspense fallback={
          <div className="space-y-5 animate-pulse">
            <div className="h-9 bg-warm-sand rounded-generous" />
            <div className="h-9 bg-warm-sand rounded-generous" />
            <div className="h-10 bg-warm-sand rounded-comfortable" />
          </div>
        }>
          <LoginForm />
        </Suspense>
      </div>

      {/* Footer */}
      <p className="mt-6 text-stone-gray text-body-sm text-center">
        {t("auth.noAccount")}{" "}
        <a
          href="/register"
          className="text-terracotta hover:text-terracotta-light underline underline-offset-2 transition-colors"
        >
          {t("auth.registerNow")}
        </a>
      </p>

      {/* Divider decoration */}
      <div className="mt-16 flex items-center gap-3 text-stone-gray">
        <div className="h-px w-12 bg-border-warm" />
        <span className="text-label tracking-widest uppercase">Cognitrix</span>
        <div className="h-px w-12 bg-border-warm" />
      </div>
    </div>
  );
}
