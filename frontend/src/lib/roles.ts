import { Eye, ShieldCheck, ShieldAlert, type LucideIcon } from "lucide-react";

export type RoleKey = "viewer" | "manager" | "admin";

export interface RoleInfo {
  key: RoleKey;
  label: string;
  email: string;
  description: string;
  icon: LucideIcon;
  accent: string; // text color class
  ring: string; // focus/border ring class
  badgeBg: string; // solid badge background class
  chipBorder: string;
  chipBg: string;
  glow: string; // box-shadow-ish glow class
  samplePrompts: string[];
}

export const ROLES: Record<RoleKey, RoleInfo> = {
  viewer: {
    key: "viewer",
    label: "Viewer",
    email: "viewer@clearancerag.test",
    description: "Public operational guidelines only",
    icon: Eye,
    accent: "text-sky-400",
    ring: "focus-visible:ring-sky-400/60",
    badgeBg: "bg-sky-500/15 text-sky-300 border-sky-500/30",
    chipBorder: "border-sky-500/30 hover:border-sky-400/60",
    chipBg: "hover:bg-sky-500/10",
    glow: "shadow-[0_0_0_1px_rgba(56,189,248,0.15)]",
    samplePrompts: [
      "What are the standard working hours?",
      "How many days of paid time off do employees get?",
      "What is the maximum pallet stacking height?",
    ],
  },
  manager: {
    key: "manager",
    label: "Manager",
    email: "manager@clearancerag.test",
    description: "Internal roadmaps and operational metrics",
    icon: ShieldCheck,
    accent: "text-amber-400",
    ring: "focus-visible:ring-amber-400/60",
    badgeBg: "bg-amber-500/15 text-amber-300 border-amber-500/30",
    chipBorder: "border-amber-500/30 hover:border-amber-400/60",
    chipBg: "hover:bg-amber-500/10",
    glow: "shadow-[0_0_0_1px_rgba(251,191,36,0.15)]",
    samplePrompts: [
      "How many packages did the Chicago hub process in Q3?",
      "What's the Q4 pipeline forecast?",
      "What is the CEO's total compensation?",
    ],
  },
  admin: {
    key: "admin",
    label: "Admin",
    email: "admin@clearancerag.test",
    description: "Full access — financials, M&A, HR",
    icon: ShieldAlert,
    accent: "text-rose-400",
    ring: "focus-visible:ring-rose-400/60",
    badgeBg: "bg-rose-500/15 text-rose-300 border-rose-500/30",
    chipBorder: "border-rose-500/30 hover:border-rose-400/60",
    chipBg: "hover:bg-rose-500/10",
    glow: "shadow-[0_0_0_1px_rgba(251,113,133,0.15)]",
    samplePrompts: [
      "What is the CEO's total compensation for FY2025?",
      "What is the estimated acquisition cost for Target Alpha?",
      "What is the total revenue for FY2025?",
    ],
  },
};

export function roleInfo(role: string | undefined | null): RoleInfo {
  if (role === "manager") return ROLES.manager;
  if (role === "admin") return ROLES.admin;
  return ROLES.viewer;
}
