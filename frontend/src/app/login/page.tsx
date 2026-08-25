"use client";

import { signIn } from "next-auth/react";
import { useState } from "react";
import { ShieldCheck, Database, Lock, Loader2, AlertCircle, ArrowRight } from "lucide-react";
import { ROLES, type RoleKey } from "@/lib/roles";
import { cn } from "@/lib/utils";

export default function LoginPage() {
  const [loading, setLoading] = useState<RoleKey | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleLogin = async (role: RoleKey) => {
    setError(null);
    setLoading(role);
    const email = ROLES[role].email;
    const result = await signIn("credentials", {
      email,
      password: email.split("@")[0] + "123",
      redirect: false,
    });

    if (result?.error) {
      setError("Login failed. The seeded demo users may not be set up yet.");
      setLoading(null);
      return;
    }

    window.location.href = "/chat";
  };

  return (
    <div className="relative min-h-screen overflow-hidden bg-neutral-950 flex flex-col items-center justify-center p-4">
      <div className="aegis-grid-bg pointer-events-none absolute inset-0" />

      <div className="relative z-10 max-w-md w-full animate-fade-up">
        <div className="rounded-2xl border border-neutral-800 bg-neutral-900/70 backdrop-blur-xl shadow-2xl shadow-black/40 overflow-hidden">
          <div className="relative p-8 pb-7 text-center border-b border-neutral-800/80">
            <div className="mx-auto relative w-16 h-16 mb-4">
              <div className="absolute inset-0 rounded-full bg-sky-500/20 blur-xl" />
              <div className="relative w-16 h-16 flex items-center justify-center rounded-full bg-neutral-800 ring-1 ring-neutral-700">
                <ShieldCheck className="w-8 h-8 text-sky-400" />
              </div>
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-neutral-50 mb-1.5">
              Aegis
            </h1>
            <p className="text-sm text-neutral-400">
              Enterprise RAG with Database-Layer RBAC
            </p>
          </div>

          <div className="p-6 sm:p-8 space-y-5">
            <div className="flex items-start gap-3 p-3.5 rounded-lg border border-neutral-800 bg-neutral-800/40">
              <Database className="w-4 h-4 text-neutral-500 mt-0.5 shrink-0" />
              <p className="text-xs text-neutral-400 leading-relaxed">
                Security lives in the database engine, not the prompt. Pick a
                clearance level below and ask the same question at every
                level to see the difference.
              </p>
            </div>

            {error && (
              <div className="flex items-center gap-2 p-3 rounded-lg border border-rose-900/60 bg-rose-950/40 text-rose-300 text-xs animate-fade-in">
                <AlertCircle className="w-4 h-4 shrink-0" />
                {error}
              </div>
            )}

            <div className="space-y-2.5">
              {(Object.keys(ROLES) as RoleKey[]).map((key) => {
                const role = ROLES[key];
                const Icon = role.icon;
                const isLoading = loading === key;
                return (
                  <button
                    key={key}
                    onClick={() => handleLogin(key)}
                    disabled={loading !== null}
                    className={cn(
                      "group relative w-full flex items-center gap-3.5 p-4 rounded-xl border bg-neutral-800/50 transition-all duration-200",
                      "hover:bg-neutral-800 hover:-translate-y-0.5 hover:shadow-lg hover:shadow-black/30",
                      "disabled:opacity-40 disabled:hover:translate-y-0 disabled:hover:shadow-none",
                      "border-neutral-700/80",
                      role.chipBorder
                    )}
                  >
                    <div
                      className={cn(
                        "flex items-center justify-center w-10 h-10 rounded-lg border shrink-0 transition-colors",
                        role.badgeBg
                      )}
                    >
                      <Icon className="w-5 h-5" />
                    </div>
                    <div className="flex flex-col text-left min-w-0">
                      <span className="font-semibold text-neutral-100 text-sm">
                        Login as {role.label}
                      </span>
                      <span className="text-xs text-neutral-500 truncate">
                        {role.description}
                      </span>
                    </div>
                    <div className="ml-auto shrink-0">
                      {isLoading ? (
                        <Loader2 className="w-4 h-4 animate-spin text-neutral-400" />
                      ) : (
                        <ArrowRight className="w-4 h-4 text-neutral-600 group-hover:text-neutral-300 group-hover:translate-x-0.5 transition-all" />
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        <div className="mt-6 flex items-center justify-center gap-2 text-[11px] text-neutral-600">
          <Lock className="w-3 h-3" />
          <span>Authenticated via Auth.js v5 &middot; JWT issued by FastAPI</span>
        </div>
      </div>
    </div>
  );
}
