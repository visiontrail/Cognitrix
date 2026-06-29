"use client";

import type { PublishedSidebarItem } from "@/lib/public/api";
import { cn } from "@/lib/utils";

export function PublicPageSidebar({
  items,
  activePageId,
  onSelectPage,
}: {
  items: PublishedSidebarItem[];
  activePageId?: string;
  onSelectPage?: (pageId: string) => void;
}) {
  return (
    <nav className="w-56 shrink-0 overflow-auto border-r border-[#e2dccf] bg-[#fffdf7] p-4 dark:border-white/10 dark:bg-[#15151b]">
      {items.map((item) => (
        <div key={item.id} className="py-1">
          <SidebarButton item={item} activePageId={activePageId} onSelectPage={onSelectPage} />
          {item.children?.map((child) => (
            <SidebarButton
              key={child.id}
              item={child}
              activePageId={activePageId}
              onSelectPage={onSelectPage}
              child
            />
          ))}
        </div>
      ))}
    </nav>
  );
}

function SidebarButton({
  item,
  activePageId,
  onSelectPage,
  child = false,
}: {
  item: PublishedSidebarItem;
  activePageId?: string;
  onSelectPage?: (pageId: string) => void;
  child?: boolean;
}) {
  const pageId = item.pageId ?? item.id;
  return (
    <button
      type="button"
      onClick={() => {
        onSelectPage?.(pageId);
        if (item.anchorRowId) {
          document
            .getElementById(item.anchorRowId)
            ?.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      }}
      className={cn(
        "block w-full rounded-md px-2 py-1 text-left text-[#2f332f] hover:bg-[#f3eadc] dark:text-gray-100 dark:hover:bg-white/10",
        child ? "ml-4 w-[calc(100%-1rem)] text-xs font-normal text-[#777166] dark:text-gray-300" : "text-sm font-semibold",
        activePageId === pageId && "bg-[#eadfca] text-[#6f4d24] dark:bg-white/15 dark:text-white"
      )}
    >
      {item.label}
    </button>
  );
}
