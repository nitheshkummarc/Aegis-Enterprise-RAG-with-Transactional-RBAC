import React from "react";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import SourcesDropdown from "@/components/SourcesDropdown";

describe("SourcesDropdown Component", () => {
  it("renders empty state correctly (0 sources)", () => {
    render(<SourcesDropdown sources={[]} userRole="viewer" />);
    
    // Should show the denied/empty message
    expect(screen.getByTestId("sources-empty")).toBeInTheDocument();
    expect(screen.getByText(/No Permitted Sources Found/i)).toBeInTheDocument();
  });

  it("renders with sources (3 sources) but no admin button for viewer", () => {
    const mockSources = [
      { document_id: "doc1", title: "Doc 1", chunk_id: "chk1" },
      { document_id: "doc2", title: "Doc 2", chunk_id: "chk2" },
      { document_id: "doc3", title: "Doc 3", chunk_id: "chk3" },
    ];
    
    render(<SourcesDropdown sources={mockSources} userRole="viewer" />);
    
    // Should show the dropdown wrapper
    expect(screen.getByTestId("sources-dropdown")).toBeInTheDocument();
    
    // Should show the count
    expect(screen.getByText(/Sources \(3\)/i)).toBeInTheDocument();
    
    // Admin button should NOT be there
    expect(screen.queryByTestId("admin-upload-btn")).not.toBeInTheDocument();
  });

  it("renders admin upload button when role is admin", () => {
    const mockSources = [
      { document_id: "doc1", title: "Admin Doc", chunk_id: "chk1" },
    ];
    
    render(<SourcesDropdown sources={mockSources} userRole="admin" />);
    
    // Admin button SHOULD be there
    expect(screen.getByTestId("admin-upload-btn")).toBeInTheDocument();
  });
});
