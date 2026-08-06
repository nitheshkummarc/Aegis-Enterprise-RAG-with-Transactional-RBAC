"use client";

import { signIn } from "next-auth/react";
import { useState } from "react";
import { Shield, Database, Lock, Loader2 } from "lucide-react";

export default function LoginPage() {
  const [loading, setLoading] = useState<string | null>(null);

  const handleLogin = async (email: string) => {
    setLoading(email);
    await signIn("credentials", {
      email,
      password: email.split("@")[0] + "123", // admin123, viewer123, etc.
      callbackUrl: "/chat",
    });
  };

  return (
    <div className="min-h-screen bg-neutral-950 flex flex-col items-center justify-center p-4">
      <div className="max-w-md w-full bg-neutral-900 border border-neutral-800 rounded-xl shadow-2xl overflow-hidden">
        
        <div className="p-8 pb-6 text-center border-b border-neutral-800 bg-neutral-900/50">
          <div className="mx-auto bg-neutral-800 w-16 h-16 flex items-center justify-center rounded-full mb-4 ring-4 ring-neutral-950">
            <Shield className="w-8 h-8 text-neutral-300" />
          </div>
          <h1 className="text-2xl font-bold text-neutral-100 mb-2">Aegis</h1>
          <p className="text-sm text-neutral-400">
            Enterprise RAG with Database-Layer RBAC
          </p>
        </div>

        <div className="p-8 space-y-6">
          <div className="flex items-start space-x-3 p-4 bg-neutral-800/50 rounded-lg border border-neutral-800">
            <Database className="w-5 h-5 text-neutral-400 mt-0.5 flex-shrink-0" />
            <p className="text-sm text-neutral-300 leading-relaxed">
              This demo proves that security should live in the database engine, not the prompt. Select a role below to see Transactional RBAC in action.
            </p>
          </div>

          <div className="space-y-3">
            <button
              onClick={() => handleLogin("admin@clearancerag.test")}
              disabled={loading !== null}
              className="w-full flex items-center justify-between p-4 rounded-lg border border-neutral-700 bg-neutral-800 hover:bg-neutral-700 transition-colors group disabled:opacity-50"
            >
              <div className="flex flex-col text-left">
                <span className="font-semibold text-neutral-100 group-hover:text-white">Login as Admin</span>
                <span className="text-xs text-neutral-400 mt-1">Full access (Financials, M&A, HR)</span>
              </div>
              {loading === "admin@clearancerag.test" ? <Loader2 className="w-5 h-5 animate-spin text-neutral-400" /> : <Lock className="w-5 h-5 text-neutral-500 group-hover:text-neutral-300" />}
            </button>

            <button
              onClick={() => handleLogin("manager@clearancerag.test")}
              disabled={loading !== null}
              className="w-full flex items-center justify-between p-4 rounded-lg border border-neutral-700 bg-neutral-800 hover:bg-neutral-700 transition-colors group disabled:opacity-50"
            >
              <div className="flex flex-col text-left">
                <span className="font-semibold text-neutral-100 group-hover:text-white">Login as Manager</span>
                <span className="text-xs text-neutral-400 mt-1">Mid access (Internal ops, roadmaps)</span>
              </div>
              {loading === "manager@clearancerag.test" ? <Loader2 className="w-5 h-5 animate-spin text-neutral-400" /> : <Lock className="w-5 h-5 text-neutral-500 group-hover:text-neutral-300" />}
            </button>

            <button
              onClick={() => handleLogin("viewer@clearancerag.test")}
              disabled={loading !== null}
              className="w-full flex items-center justify-between p-4 rounded-lg border border-neutral-700 bg-neutral-800 hover:bg-neutral-700 transition-colors group disabled:opacity-50"
            >
              <div className="flex flex-col text-left">
                <span className="font-semibold text-neutral-100 group-hover:text-white">Login as Viewer</span>
                <span className="text-xs text-neutral-400 mt-1">Low access (Public guidelines only)</span>
              </div>
              {loading === "viewer@clearancerag.test" ? <Loader2 className="w-5 h-5 animate-spin text-neutral-400" /> : <Lock className="w-5 h-5 text-neutral-500 group-hover:text-neutral-300" />}
            </button>
          </div>
        </div>
        
      </div>
      
      <p className="mt-8 text-xs text-neutral-500">
        Authentication powered by Auth.js v5 (NextAuth)
      </p>
    </div>
  );
}
