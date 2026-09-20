import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import StatusBadge from "@/components/StatusBadge";

describe("StatusBadge", () => {
  it("renders the status text", () => {
    render(<StatusBadge status="Approved" />);
    expect(screen.getByText("Approved")).toBeInTheDocument();
  });

  it("falls back to a default style for an unrecognized status", () => {
    render(<StatusBadge status="Unknown Status" />);
    expect(screen.getByText("Unknown Status")).toBeInTheDocument();
  });
});
