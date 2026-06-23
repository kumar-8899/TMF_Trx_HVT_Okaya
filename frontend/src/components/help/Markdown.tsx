/** Markdown renderer for help docs (react-markdown + GFM), themed to MUI. */
import { Box } from "@mui/material";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { MONO_STACK } from "../../theme/theme";

export function Markdown({ children }: { children: string }) {
  return (
    <Box
      sx={{
        "& h1": { fontSize: 26, fontWeight: 700, mt: 0, mb: 1.5 },
        "& h2": { fontSize: 20, fontWeight: 700, mt: 3, mb: 1, borderBottom: "1px solid", borderColor: "divider", pb: 0.5 },
        "& h3": { fontSize: 16, fontWeight: 700, mt: 2, mb: 0.75 },
        "& p, & li": { fontSize: 14, lineHeight: 1.6 },
        "& a": { color: "info.main" },
        "& code": { fontFamily: MONO_STACK, fontSize: 12.5, bgcolor: "action.hover", px: 0.5, py: 0.1, borderRadius: 0.5 },
        "& pre": { bgcolor: "action.hover", p: 1.5, borderRadius: 1, overflowX: "auto" },
        "& pre code": { bgcolor: "transparent", p: 0 },
        "& table": { borderCollapse: "collapse", width: "100%", my: 1.5, fontSize: 13 },
        "& th, & td": { border: "1px solid", borderColor: "divider", p: "5px 9px", textAlign: "left" },
        "& th": { bgcolor: "action.hover", fontWeight: 700 },
        "& blockquote": { borderLeft: "3px solid", borderColor: "divider", m: 0, pl: 1.5, color: "text.secondary" },
        "& img": { maxWidth: "100%" },
      }}
    >
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </Box>
  );
}
