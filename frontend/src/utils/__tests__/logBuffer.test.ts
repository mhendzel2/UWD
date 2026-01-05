import { describe, expect, it } from "vitest";
import { LOG_BUFFER_LIMIT, appendLog, formatLogMessage } from "../logBuffer";

describe("logBuffer", () => {
  it("appends and trims to limit", () => {
    const base = Array.from({ length: LOG_BUFFER_LIMIT }, (_, idx) => ({
      message: `m${idx}`,
      timestamp: idx,
      level: "info" as const,
    }));
    const result = appendLog(base, { message: "new", timestamp: 9999, level: "error" });
    expect(result).toHaveLength(LOG_BUFFER_LIMIT);
    expect(result[0].message).toBe("new");
    expect(result[result.length - 1].message).toBe("m498");
  });

  it("formats log message with level and time", () => {
    const ts = Date.now();
    const message = formatLogMessage({ message: "hello", level: "warning", timestamp: ts });
    expect(message).toContain("WARNING");
    expect(message).toContain("hello");
  });
});
