import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import StatCard from "@/components/StatCard";

describe("StatCard", () => {
  it("renders the label and value", () => {
    render(<StatCard label="Pending review" value={5} />);
    expect(screen.getByText("Pending review")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
  });
});
