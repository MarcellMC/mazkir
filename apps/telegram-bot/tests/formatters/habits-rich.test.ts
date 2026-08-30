import { describe, it, expect } from "vitest";
import { buildHabitsRich } from "../../src/formatters/habits-rich.js";

const habit = (o: object) => ({
  name: "Dog walk", frequency: "daily", streak: 3,
  tokens_per_completion: 5, completed_today: false, ...o,
});
const html = (h: unknown[]) => buildHabitsRich(h as never).html ?? "";

describe("buildHabitsRich", () => {
  it("offers a complete button only for habits not yet done", () => {
    const out = html([
      habit({ name: "Dog walk", completed_today: false }),
      habit({ name: "Workout", completed_today: true }),
    ]);
    expect(out).toContain('data="habit:complete:Dog walk"');
    expect(out).not.toContain('data="habit:complete:Workout"');
  });

  it("keeps the streak from the old formatter", () => {
    const out = html([habit({ streak: 7 })]);
    expect(out).toContain("7");
  });

  it("escapes habit names in the body", () => {
    const out = html([habit({ name: "Read <Dune> & rest" })]);
    expect(out).toContain("Read &lt;Dune&gt; &amp; rest");
  });

  it("renders a body even when every habit is done", () => {
    const out = html([habit({ completed_today: true })]);
    expect(out).toContain("Dog walk");
    expect(out).not.toContain("<tg-button-row");
  });
});
