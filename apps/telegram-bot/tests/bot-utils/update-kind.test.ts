import { describe, it, expect } from "vitest";
import { updateKind } from "../../src/bot-utils/update-kind.js";

const loc = { latitude: 32.08, longitude: 34.78 };

describe("updateKind", () => {
  it("labels each kind of update", () => {
    expect(updateKind({ message: { text: "hi" } } as any)).toBe("text");
    expect(updateKind({ message: { photo: [{}] } } as any)).toBe("photo");
    expect(updateKind({ editedMessage: { location: loc } } as any)).toBe("live_location");
    expect(updateKind({ message: { location: { ...loc, live_period: 900 } } } as any)).toBe("live_location");
    expect(updateKind({ message: { location: loc } } as any)).toBe("location");
    expect(updateKind({ callbackQuery: { data: "x" } } as any)).toBe("callback");
    expect(updateKind({} as any)).toBe("other");
  });

  it("an edited text message is other, not live_location", () => {
    expect(updateKind({ editedMessage: { text: "fixed typo" } } as any)).toBe("other");
  });
});
