"use client";

import { useQuery } from "@tanstack/react-query";
import { useAssetStore } from "@/stores/asset-store";

export function useChartAssets() {
  const setAssets = useAssetStore((s) => s.setAssets);

  return useQuery({
    queryKey: ["chart-assets"],
    queryFn: async () => {
      // The store is the live view; cross-device hydration happens once per
      // workspace in AppShell (hydrateWorkspaceStateFromServer). This query just
      // mirrors the store and re-runs idempotently on invalidation.
      const assets = useAssetStore.getState().assets;
      setAssets(assets);
      return assets;
    },
  });
}

export function useChartAsset(assetId: string | null) {
  return useQuery({
    queryKey: ["chart-asset", assetId],
    queryFn: () => {
      if (!assetId) {
        return null;
      }
      return useAssetStore.getState().getAsset(assetId) ?? null;
    },
    enabled: !!assetId,
  });
}
