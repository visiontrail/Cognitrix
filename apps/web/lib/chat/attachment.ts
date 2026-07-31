/**
 * Chat composer attachment rules.
 *
 * The write-ingestion backend accepts exactly ONE workbook per request
 * (`POST /ingestion/uploads` rejects anything else with `SINGLE_FILE_ONLY`, and
 * an ingestion job maps 1:1 onto a single upload row). A workbook may still
 * decompose into several target tables — that is handled server-side through the
 * multi-proposal approval queue — but multiple files in one turn is not a
 * supported shape. So the composer enforces the single-file rule up front and
 * explains it instead of letting the request fail at the API boundary.
 */

export const ALLOWED_ATTACHMENT_EXTENSIONS = [".xlsx"] as const;

/** Mirrors `MAX_FILE_SIZE_BYTES` in `apps/api/agentic_ingestion/uploads.py`. */
export const MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024;
export const MAX_ATTACHMENT_MB = MAX_ATTACHMENT_BYTES / (1024 * 1024);

export type AttachmentNoticeLevel = "warning" | "error";

export type AttachmentNotice = {
  level: AttachmentNoticeLevel;
  /** i18n key; the caller renders it through `t()` so copy stays localized. */
  key: string;
  params: Record<string, string | number>;
};

export type AttachmentSelection = {
  /** The single file to attach, or `null` when nothing usable was provided. */
  file: File | null;
  /** User-facing explanation when files were dropped, ignored, or rejected. */
  notice: AttachmentNotice | null;
};

export function isSupportedAttachment(file: File): boolean {
  const name = file.name.toLowerCase();
  return ALLOWED_ATTACHMENT_EXTENSIONS.some((extension) => name.endsWith(extension));
}

/**
 * Reduce whatever the user dropped/picked to at most one usable workbook.
 *
 * Never silently swallows input: any ignored or rejected file produces a notice
 * the composer surfaces as a toast.
 */
export function selectChatAttachment(files: readonly File[]): AttachmentSelection {
  if (files.length === 0) {
    return { file: null, notice: null };
  }

  const supported = files.filter(isSupportedAttachment);
  if (supported.length === 0) {
    return {
      file: null,
      notice: {
        level: "error",
        key: "chat.attachment.unsupportedType",
        params: {
          fileName: files[0].name,
          allowed: ALLOWED_ATTACHMENT_EXTENSIONS.join(", "),
        },
      },
    };
  }

  const withinSizeLimit = supported.filter((file) => file.size <= MAX_ATTACHMENT_BYTES);
  if (withinSizeLimit.length === 0) {
    return {
      file: null,
      notice: {
        level: "error",
        key: "chat.attachment.tooLarge",
        params: {
          fileName: supported[0].name,
          maxSizeMb: MAX_ATTACHMENT_MB,
        },
      },
    };
  }

  const [file] = withinSizeLimit;
  const ignoredCount = files.length - 1;
  if (ignoredCount > 0) {
    return {
      file,
      notice: {
        level: "warning",
        key: "chat.attachment.singleFileOnly",
        params: { fileName: file.name, ignoredCount },
      },
    };
  }

  return { file, notice: null };
}

/** Extract dropped files from a DataTransfer, tolerating the items-only shape. */
export function filesFromDataTransfer(dataTransfer: DataTransfer | null): File[] {
  if (!dataTransfer) return [];
  if (dataTransfer.files && dataTransfer.files.length > 0) {
    return Array.from(dataTransfer.files);
  }
  if (dataTransfer.items && dataTransfer.items.length > 0) {
    return Array.from(dataTransfer.items)
      .filter((item) => item.kind === "file")
      .map((item) => item.getAsFile())
      .filter((file): file is File => file !== null);
  }
  return [];
}

/** True when a drag operation carries files (as opposed to text or an element). */
export function dragCarriesFiles(dataTransfer: DataTransfer | null): boolean {
  if (!dataTransfer) return false;
  const types = dataTransfer.types;
  if (!types) return false;
  return Array.from(types as ArrayLike<string>).includes("Files");
}
