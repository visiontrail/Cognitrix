import { describe, expect, it } from "vitest";

import {
  MAX_ATTACHMENT_BYTES,
  isSupportedAttachment,
  selectChatAttachment,
} from "../../lib/chat/attachment";

function makeFile(name: string, size = 1024): File {
  const file = new File(["x"], name, {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  Object.defineProperty(file, "size", { value: size });
  return file;
}

describe("selectChatAttachment", () => {
  it("returns nothing for an empty selection", () => {
    expect(selectChatAttachment([])).toEqual({ file: null, notice: null });
  });

  it("accepts a single .xlsx file without a notice", () => {
    const file = makeFile("headcount.xlsx");
    expect(selectChatAttachment([file])).toEqual({ file, notice: null });
  });

  it("keeps only the first file and warns when several are dropped", () => {
    const first = makeFile("q1.xlsx");
    const second = makeFile("q2.xlsx");
    const third = makeFile("q3.xlsx");

    const result = selectChatAttachment([first, second, third]);

    expect(result.file).toBe(first);
    expect(result.notice).toEqual({
      level: "warning",
      key: "chat.attachment.singleFileOnly",
      params: { fileName: "q1.xlsx", ignoredCount: 2 },
    });
  });

  it("skips unsupported files and keeps the first supported one", () => {
    const csv = makeFile("notes.csv");
    const xlsx = makeFile("headcount.xlsx");

    const result = selectChatAttachment([csv, xlsx]);

    expect(result.file).toBe(xlsx);
    expect(result.notice?.level).toBe("warning");
  });

  it("rejects a selection with no supported file type", () => {
    const result = selectChatAttachment([makeFile("report.pdf"), makeFile("data.csv")]);

    expect(result.file).toBeNull();
    expect(result.notice).toMatchObject({
      level: "error",
      key: "chat.attachment.unsupportedType",
      params: { fileName: "report.pdf" },
    });
  });

  it("rejects files above the backend size limit", () => {
    const result = selectChatAttachment([makeFile("huge.xlsx", MAX_ATTACHMENT_BYTES + 1)]);

    expect(result.file).toBeNull();
    expect(result.notice).toMatchObject({
      level: "error",
      key: "chat.attachment.tooLarge",
      params: { fileName: "huge.xlsx", maxSizeMb: 10 },
    });
  });

  it("falls back to a smaller sibling when the first file is oversized", () => {
    const oversized = makeFile("huge.xlsx", MAX_ATTACHMENT_BYTES + 1);
    const usable = makeFile("small.xlsx");

    const result = selectChatAttachment([oversized, usable]);

    expect(result.file).toBe(usable);
    expect(result.notice?.key).toBe("chat.attachment.singleFileOnly");
  });

  it("matches the extension case-insensitively", () => {
    expect(isSupportedAttachment(makeFile("Headcount.XLSX"))).toBe(true);
    expect(isSupportedAttachment(makeFile("headcount.xls"))).toBe(false);
  });
});
