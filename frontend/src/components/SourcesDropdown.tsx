import React, { useState } from "react";
import { ChevronDown, ChevronRight, UploadCloud, Shield } from "lucide-react";

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
      <div className="mt-4 p-4 bg-red-950/30 border border-red-900 rounded-lg" data-testid="sources-empty">
        <div className="flex items-center text-red-400 font-medium">
          <Shield className="w-5 h-5 mr-2" />
          No Permitted Sources Found
        </div>
        <p className="text-red-500 text-sm mt-1">
          You do not have the required clearance level to access information for this query.
        </p>
      </div>
    );
  }

  return (
    <div className="mt-4 border border-neutral-800 rounded-lg overflow-hidden bg-neutral-900" data-testid="sources-dropdown">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between p-3 bg-neutral-800 hover:bg-neutral-700 transition-colors"
      >
        <span className="font-medium text-neutral-200 flex items-center">
          {isOpen ? <ChevronDown className="w-4 h-4 mr-2" /> : <ChevronRight className="w-4 h-4 mr-2" />}
          Sources ({sources.length})
        </span>
        
        {/* Role-Conditional UI Element: Only visible to admins */}
        {userRole === "admin" && (
          <span className="flex items-center text-xs font-semibold text-neutral-300 bg-neutral-700 px-2 py-1 rounded" data-testid="admin-upload-btn">
            <UploadCloud className="w-3 h-3 mr-1" />
            Admin Upload
          </span>
        )}
      </button>

      {isOpen && (
        <div className="p-3 border-t border-neutral-800" data-testid="sources-list">
          <ul className="space-y-2">
            {sources.map((source, idx) => (
              <li key={idx} className="text-sm text-neutral-300 bg-neutral-800 p-2 rounded">
                <span className="font-semibold text-neutral-100">{source.title}</span> 
                <span className="text-xs text-neutral-500 ml-2">ID: {source.document_id.slice(0, 8)}...</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
