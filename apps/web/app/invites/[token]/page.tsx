"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { getInMemoryToken } from "@/lib/auth/session";
import { useI18n } from "@/lib/i18n/context";
import { acceptInvite } from "@/lib/workspace/collaboration";

export default function InviteAcceptPage() {
  const { t } = useI18n();
  const params = useParams();
  const router = useRouter();
  const token = typeof params.token === "string" ? params.token : Array.isArray(params.token) ? params.token[0] : "";
  const [status, setStatus] = useState<"loading" | "error" | "success">("loading");
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!token) return;

    const sessionToken = getInMemoryToken();
    if (!sessionToken) {
      // Not logged in — redirect to register with invite
      router.replace(`/register?invite=${encodeURIComponent(token)}`);
      return;
    }

    acceptInvite(token)
      .then(() => {
        setStatus("success");
        setTimeout(() => {
          router.push("/");
        }, 1500);
      })
      .catch((err: any) => {
        const code = err.code ?? "invite_failed";
        if (code === "invite_expired") {
          setMessage(t("invite.expired"));
        } else if (code === "invite_revoked") {
          setMessage(t("invite.revoked"));
        } else if (code === "invite_exhausted") {
          setMessage(t("invite.exhausted"));
        } else {
          setMessage(t("invite.invalid"));
        }
        setStatus("error");
      });
  }, [token, router, t]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="text-center space-y-4">
        {status === "loading" && <p className="text-muted-foreground">{t("invite.processing")}</p>}
        {status === "success" && <p className="text-green-600">{t("invite.accepted")}</p>}
        {status === "error" && (
          <div className="space-y-2">
            <p className="text-destructive">{message}</p>
            <Link href="/" className="text-sm text-primary underline">{t("invite.backHome")}</Link>
          </div>
        )}
      </div>
    </div>
  );
}
