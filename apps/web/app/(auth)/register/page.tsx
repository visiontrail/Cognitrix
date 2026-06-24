"use client";

import { Suspense, useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Globe, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { API_BASE_URL } from "@/lib/api-base";
import { apiRegister, AuthError } from "@/lib/auth/auth-client";
import { useI18n } from "@/lib/i18n/context";
import { SUPPORTED_LOCALES, type Locale } from "@/lib/i18n/dictionary";

const LOCALE_LABELS: Record<Locale, string> = {
  "en-US": "English",
  "zh-CN": "中文",
};

type JobOption = { id: number; code: string; label_zh: string; label_en: string };

function LanguageSwitcher() {
  const { locale, setLocale } = useI18n();

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

function RegisterForm() {
  const router = useRouter();
  const { t, locale } = useI18n();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [jobId, setJobId] = useState<number | "">("");
  const [jobs, setJobs] = useState<JobOption[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showSuccess, setShowSuccess] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE_URL}/jobs`)
      .then((r) => r.json())
      .then((data) => setJobs(data.jobs ?? []))
      .catch(() => {});
  }, []);

  function jobLabel(j: JobOption) {
    return locale === "zh-CN" ? j.label_zh : (j.label_en || j.label_zh);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!jobId) { setError(t("auth.jobRequired")); return; }
    if (password.length < 8) { setError(t("auth.passwordTooShort", { n: 8 })); return; }
    setLoading(true);
    try {
      await apiRegister({
        email,
        password,
        display_name: displayName,
        job_id: Number(jobId),
      });
      setShowSuccess(true);
    } catch (err) {
      setLoading(false);
      if (err instanceof AuthError) {
        if (err.code === "email_taken") setError(t("auth.emailTaken"));
        else if (err.code === "password_too_short") setError(t("auth.passwordTooShort", { n: 8 }));
        else setError(err.message || t("auth.registerError"));
      } else {
        setError(t("auth.registerError"));
      }
    }
  }

  function handleSuccessConfirm() {
    router.push("/login");
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
        <label htmlFor="displayName" className="block text-label font-medium text-charcoal-warm tracking-wide uppercase">
          {t("auth.displayName")}
        </label>
        <Input
          id="displayName"
          type="text"
          autoComplete="name"
          placeholder={t("auth.namePlaceholder")}
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          required
        />
      </div>

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
        <label htmlFor="password" className="block text-label font-medium text-charcoal-warm tracking-wide uppercase">
          {t("auth.password")}
        </label>
        <Input
          id="password"
          type="password"
          autoComplete="new-password"
          placeholder={t("auth.passwordPlaceholder")}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          minLength={8}
        />
      </div>

      <div className="space-y-1.5">
        <label htmlFor="job" className="block text-label font-medium text-charcoal-warm tracking-wide uppercase">
          {t("auth.job")}
        </label>
        <select
          id="job"
          className="flex h-9 w-full rounded-generous border border-border-cream bg-ivory px-3 py-1 text-body-sm text-near-black shadow-ring-border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-blue focus-visible:border-focus-blue placeholder:text-stone-gray"
          value={jobId}
          onChange={(e) => setJobId(e.target.value ? Number(e.target.value) : "")}
          required
        >
          <option value="" className="text-stone-gray">{t("auth.selectJob")}</option>
          {jobs.map((j) => (
            <option key={j.id} value={j.id}>
              {jobLabel(j)}
            </option>
          ))}
        </select>
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
            {t("auth.registering")}
          </span>
        ) : (
          t("auth.createAccount")
        )}
      </Button>

      <Dialog open={showSuccess} onOpenChange={() => {}}>
        <DialogContent
          className="max-w-xs text-center [&>button.absolute]:hidden"
          onPointerDownOutside={(e) => e.preventDefault()}
          onEscapeKeyDown={(e) => e.preventDefault()}
        >
          <DialogHeader className="items-center">
            <CheckCircle2 className="h-10 w-10 text-green-600 mb-2" />
            <DialogTitle>{t("auth.registerSuccess")}</DialogTitle>
            <DialogDescription>{t("auth.registerSuccessDesc")}</DialogDescription>
          </DialogHeader>
          <Button
            className="w-full h-10 text-body font-medium mt-2"
            onClick={handleSuccessConfirm}
          >
            {t("auth.goToLogin")}
          </Button>
        </DialogContent>
      </Dialog>
    </form>
  );
}

export default function RegisterPage() {
  const { t } = useI18n();

  return (
    <div className="relative min-h-screen bg-parchment flex flex-col items-center justify-center p-6">
      <LanguageSwitcher />

      {/* Brand */}
      <div className="mb-10 text-center">
        <div className="inline-flex items-baseline gap-2 mb-3">
          <span className="font-serif text-[1.6rem] font-[500] leading-none text-near-black">Cognitrix</span>
        </div>
        <h1 className="font-serif text-heading text-near-black">{t("auth.createAccount")}</h1>
        <p className="mt-2 text-olive-gray text-body">{t("auth.registerSubtitle")}</p>
      </div>

      {/* Card */}
      <div className="w-full max-w-sm bg-ivory rounded-very border border-border-cream shadow-whisper px-8 py-9">
        <Suspense fallback={
          <div className="space-y-5 animate-pulse">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="h-9 bg-warm-sand rounded-generous" />
            ))}
            <div className="h-10 bg-warm-sand rounded-comfortable" />
          </div>
        }>
          <RegisterForm />
        </Suspense>
      </div>

      {/* Footer */}
      <p className="mt-6 text-stone-gray text-body-sm text-center">
        {t("auth.hasAccount")}{" "}
        <a
          href="/login"
          className="text-terracotta hover:text-terracotta-light underline underline-offset-2 transition-colors"
        >
          {t("auth.loginNow")}
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
