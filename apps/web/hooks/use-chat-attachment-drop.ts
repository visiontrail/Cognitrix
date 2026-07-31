"use client";

import { useCallback, useRef, useState } from "react";
import type { DragEvent } from "react";
import { toast } from "sonner";
import { useChatStore } from "@/stores/chat-store";
import { useUIStore } from "@/stores/ui-store";
import { useI18n } from "@/lib/i18n/context";
import {
  dragCarriesFiles,
  filesFromDataTransfer,
  selectChatAttachment,
} from "@/lib/chat/attachment";

type DropHandlers = {
  onDragEnter: (event: DragEvent<HTMLElement>) => void;
  onDragOver: (event: DragEvent<HTMLElement>) => void;
  onDragLeave: (event: DragEvent<HTMLElement>) => void;
  onDrop: (event: DragEvent<HTMLElement>) => void;
};

export type ChatAttachmentDropZone = {
  /** True while a file drag hovers the zone — drives the drop overlay. */
  isDragActive: boolean;
  /** True when a drop would be refused (no session / streaming / awaiting confirmation). */
  isBlocked: boolean;
  dropHandlers: DropHandlers;
};

/**
 * Panel-wide drag-and-drop for a single Excel workbook.
 *
 * The accepted file lands in `chat-store.composerAttachment`, which the composer
 * renders as its attachment chip — so dropping anywhere over the conversation is
 * equivalent to picking a file from the "+" menu.
 */
export function useChatAttachmentDropZone(sessionId: string | null): ChatAttachmentDropZone {
  const { t } = useI18n();
  const setComposerAttachment = useChatStore((s) => s.setComposerAttachment);
  const isSending = useUIStore((s) => (sessionId ? Boolean(s.sendingBySession[sessionId]) : false));
  const pendingApproval = useChatStore((s) =>
    sessionId ? s.pendingIngestionBySession[sessionId] : undefined
  );
  const pendingSetup = useChatStore((s) =>
    sessionId ? s.pendingIngestionSetupBySession[sessionId] : undefined
  );
  const [isDragActive, setIsDragActive] = useState(false);
  // dragenter/dragleave fire for every nested element; count depth so the
  // overlay does not flicker while the pointer crosses children.
  const dragDepth = useRef(0);

  const blockedReasonKey = !sessionId
    ? "chat.attachment.noSession"
    : pendingApproval || pendingSetup
    ? "chat.attachment.pendingIngestion"
    : isSending
    ? "chat.attachment.busy"
    : null;

  const resetDrag = useCallback(() => {
    dragDepth.current = 0;
    setIsDragActive(false);
  }, []);

  const onDragEnter = useCallback((event: DragEvent<HTMLElement>) => {
    if (!dragCarriesFiles(event.dataTransfer)) return;
    event.preventDefault();
    dragDepth.current += 1;
    setIsDragActive(true);
  }, []);

  const onDragOver = useCallback(
    (event: DragEvent<HTMLElement>) => {
      if (!dragCarriesFiles(event.dataTransfer)) return;
      // Required, otherwise the browser opens the file instead of dropping it.
      event.preventDefault();
      if (event.dataTransfer) {
        event.dataTransfer.dropEffect = blockedReasonKey ? "none" : "copy";
      }
      if (dragDepth.current === 0) {
        dragDepth.current = 1;
      }
      setIsDragActive(true);
    },
    [blockedReasonKey]
  );

  const onDragLeave = useCallback((event: DragEvent<HTMLElement>) => {
    if (!dragCarriesFiles(event.dataTransfer)) return;
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) {
      setIsDragActive(false);
    }
  }, []);

  const onDrop = useCallback(
    (event: DragEvent<HTMLElement>) => {
      if (!dragCarriesFiles(event.dataTransfer)) return;
      event.preventDefault();
      resetDrag();

      if (blockedReasonKey) {
        toast.info(t(blockedReasonKey));
        return;
      }

      const { file, notice } = selectChatAttachment(filesFromDataTransfer(event.dataTransfer));
      if (notice) {
        const message = t(notice.key, notice.params);
        if (notice.level === "error") {
          toast.error(message);
        } else {
          toast.warning(message);
        }
      }
      if (file) {
        setComposerAttachment(file);
      }
    },
    [blockedReasonKey, resetDrag, setComposerAttachment, t]
  );

  return {
    isDragActive,
    isBlocked: blockedReasonKey !== null,
    dropHandlers: { onDragEnter, onDragOver, onDragLeave, onDrop },
  };
}
