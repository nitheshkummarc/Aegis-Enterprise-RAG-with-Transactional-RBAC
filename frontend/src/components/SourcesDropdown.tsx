import React, { useState } from "react";
import { ChevronDown, ChevronRight, UploadCloud, ShieldAlert, FileText } from "lucide-react";
import { cn } from "@/lib/utils";

export type Source = {
  document_id: string;
  title: string;
  chunk_id: string;
};

interface SourcesDropdownProps {
  sources: Source[];
  userRole: string; // Used to conditionally render the admin upload button
}

export default function SourcesDropdown({ sources, userRole }: SourcesDropdownProps) {
  const [isOpen, setIsOpen] = useState(false);

  // If there are no sources, access was denied or nothing was found.
  if (!sources || sources.length === 0) {
    return (
      <div
        className="mt-3 flex items-start gap-3 p-3.5 rounded-xl border border-rose-900/50 bg-rose-950/25 animate-fade-in"
        data-testid="sources-empty"
      >
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-rose-500/15 shrink-0">
          <ShieldAlert className="w-4 h-4 text-rose-400" />
        </div>
        <div>
          <p className="text-sm font-medium text-rose-300">No Permitted Sources Found</p>
          <p className="text-xs text-rose-400/80 mt-0.5">
            Your clearance level does not permit access to information for this query.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div
      className="mt-3 rounded-xl border border-neutral-800 overflow-hidden bg-neutral-900/60 animate-fade-in"
      data-testid="sources-dropdown"
    >
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between p-3 hover:bg-neutral-800/60 transition-colors"
      >
        <span className="text-xs font-medium text-neutral-300 flex items-center gap-1.5">
          {isOpen ? (
            <ChevronDown className="w-3.5 h-3.5 text-neutral-500" />
          ) : (
            <ChevronRight className="w-3.5 h-3.5 text-neutral-500" />
          )}
          Sources ({sources.length})
        </span>

        {/* Role-Conditional UI Element: Only visible to admins */}
        {userRole === "admin" && (
          <span
            className="flex items-center gap-1 text-[10px] font-semibold text-rose-300 bg-rose-500/10 border border-rose-500/20 px-2 py-1 rounded-md"
            data-testid="admin-upload-btn"
          >
            <UploadCloud className="w-3 h-3" />
            Admin Upload
          </span>
        )}
      </button>

      {isOpen && (
        <div
          className="p-2.5 pt-0 border-t border-neutral-800/80 space-y-1.5"
          data-testid="sources-list"
        >
          {sources.map((source, idx) => (
            <div
              key={source.chunk_id || idx}
              className={cn(
                "flex items-center gap-2.5 text-xs text-neutral-300 bg-neutral-800/40 hover:bg-neutral-800/70",
                "p-2.5 rounded-lg border border-neutral-800 transition-colors"
              )}
            >
              <FileText className="w-3.5 h-3.5 text-neutral-500 shrink-0" />
              <span className="font-medium text-neutral-100 truncate">{source.title}</span>
              <span className="ml-auto text-[10px] text-neutral-600 font-mono shrink-0">
                {source.document_id.slice(0, 8)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
