/** A shared-library image (`![alt](asset:<id>)` in help markdown). The bytes come from the
 * authenticated `/help/asset/<id>` route (an <img src> can't send the bearer header), so it is
 * fetched as a blob. Shows where/when it was captured and warns when the screen it depicts has
 * changed since (docs/assets/manifest.json → `stale`, computed server-side in a source checkout). */
import { Alert, Box, Chip, Stack, Typography } from "@mui/material";
import { useEffect, useState } from "react";

import { api } from "../../api/client";

export interface AssetInfo {
  id: string;
  alt: string;
  audience: string;
  framework_version: string | null;
  route: string | null;
  stale: boolean;
}

let metaPromise: Promise<Record<string, AssetInfo>> | null = null;
const blobUrls = new Map<string, Promise<string>>();

/** Test hook: forget cached manifest + blob URLs. */
export function resetHelpImageCache(): void {
  metaPromise = null;
  blobUrls.clear();
}

function loadMeta(): Promise<Record<string, AssetInfo>> {
  if (!metaPromise) {
    metaPromise = api.get("/help/assets")
      .then((rows: AssetInfo[]) => Object.fromEntries(rows.map((r) => [r.id, r])))
      .catch(() => ({}));
  }
  return metaPromise;
}

function loadBlobUrl(id: string): Promise<string> {
  let p = blobUrls.get(id);
  if (!p) {
    p = api.getBlob(`/help/asset/${encodeURIComponent(id)}`).then((b) => URL.createObjectURL(b));
    blobUrls.set(id, p);
    p.catch(() => blobUrls.delete(id));
  }
  return p;
}

export function HelpImage({ id, alt }: { id: string; alt?: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [meta, setMeta] = useState<AssetInfo | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    loadBlobUrl(id).then((u) => alive && setUrl(u)).catch(() => alive && setFailed(true));
    loadMeta().then((m) => alive && setMeta(m[id] ?? null));
    return () => { alive = false; };
  }, [id]);

  if (failed) return <Alert severity="warning" sx={{ my: 1 }}>Image <code>{id}</code> is not available.</Alert>;
  const caption = alt || meta?.alt || "";
  return (
    <Box component="figure" sx={{ m: 0, my: 2 }}>
      {url ? (
        <Box component="img" src={url} alt={caption}
          sx={{ maxWidth: "100%", border: "1px solid", borderColor: "divider", borderRadius: 1, display: "block" }} />
      ) : (
        <Box sx={{ height: 120, bgcolor: "action.hover", borderRadius: 1 }} aria-busy="true" />
      )}
      <Stack component="figcaption" direction="row" spacing={1} alignItems="center" flexWrap="wrap" sx={{ mt: 0.75 }}>
        {caption && <Typography variant="caption" color="text.secondary">{caption}</Typography>}
        {meta?.framework_version && <Chip size="small" variant="outlined" label={`captured at v${meta.framework_version}`} />}
        {meta?.stale && <Chip size="small" color="warning" label="screen changed since capture" />}
      </Stack>
    </Box>
  );
}
