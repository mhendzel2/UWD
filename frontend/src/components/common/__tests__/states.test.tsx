import { render, screen } from "@testing-library/react";
import React from "react";
import { describe, it, expect, vi } from "vitest";
import LoadingState from "../LoadingState";
import ErrorState from "../ErrorState";
import EmptyState from "../EmptyState";

describe("shared states", () => {
  it("renders loading state with label", () => {
    render(<LoadingState label="Fetching data" />);
    expect(screen.getByText("Fetching data")).toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("renders error state and retry control", () => {
    const retry = vi.fn();
    render(<ErrorState message="boom" onRetry={retry} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    screen.getByRole("button", { name: /retry/i }).click();
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it("renders empty state", () => {
    render(<EmptyState title="Nothing here" description="Add a session" />);
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
    expect(screen.getByText("Add a session")).toBeInTheDocument();
  });
});
