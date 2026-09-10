import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { JOURNEY, REPORT } from "../../state/mock";

import { JourneyFlow } from "../JourneyFlow";

afterEach(cleanup);

describe("JourneyFlow", () => {
  it("shows the event text instead of its action as the node label", () => {
    const node = JOURNEY[0];

    render(
      <JourneyFlow
        report={{
          ...REPORT,
          journey: [node],
          lanes: [{ id: node.lane, label: "앱 행동" }],
        }}
        onOpenEvidence={vi.fn()}
      />,
    );

    const nodeButton = screen.getByTitle(node.text);
    expect(nodeButton).toHaveTextContent(node.text);
    expect(nodeButton).not.toHaveTextContent(node.action);
  });
});
