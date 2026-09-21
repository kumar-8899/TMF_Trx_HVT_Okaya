/** Markdown renderer for help docs (react-markdown + GFM), themed to MUI.
 *
 * Beyond plain markdown it understands four help-specific conventions:
 *   - `![alt](asset:<id>)`   a shared-library image (screenshot/diagram) — see HelpImage
 *   - `[text](help:<page-id>#anchor)`  in-app link to another help page (deep link `/help?page=`)
 *   - ```` ```tmf:<widget> ````  a live interactive widget (see widgets/index.tsx)
 *   - heading anchors + a copy button on code blocks */
import Check from "@mui/icons-material/Check";
import ContentCopy from "@mui/icons-material/ContentCopy";
import { Box, IconButton, Tooltip } from "@mui/material";
import { Children, createContext, isValidElement, useContext, useState, type ReactElement, type ReactNode } from "react";
import ReactMarkdown, { defaultUrlTransform, type Components } from "react-markdown";
import { useNavigate } from "react-router-dom";
import remarkGfm from "remark-gfm";

import { MONO_STACK } from "../../theme/theme";
import { HelpImage } from "./HelpImage";
import { HelpWidget } from "./widgets";

/** Where `help:<id>` links navigate. `/help` by default; the Portal's embedded manual sets
 * `/portal?tab=manual` so a reader stays inside the portal. */
export const HelpLinkBase = createContext("/help");

export function helpLink(base: string, id: string, anchor?: string): string {
  return `${base}${base.includes("?") ? "&" : "?"}page=${id}${anchor ? `#${anchor}` : ""}`;
}

/** Flatten React children to their text (heading slugs, code-block copy, widget args). */
export function textOf(node: ReactNode): string {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (isValidElement(node)) return textOf((node.props as { children?: ReactNode }).children);
  return "";
}

export function slugify(text: string): string {
  return text.toLowerCase().trim().replace(/[^\w\s-]/g, "").replace(/\s+/g, "-");
}

/** react-markdown strips unknown URL schemes; let our two through. */
function urlTransform(url: string): string {
  return url.startsWith("help:") || url.startsWith("asset:") ? url : defaultUrlTransform(url);
}

function CodeBlock({ children }: { children: ReactNode }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    void navigator.clipboard?.writeText(textOf(children).replace(/\n$/, "")).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    });
  };
  return (
    <Box sx={{ position: "relative", "&:hover .copy-btn": { opacity: 1 } }}>
      <pre>{children}</pre>
      <Tooltip title={copied ? "Copied" : "Copy"}>
        <IconButton className="copy-btn" size="small" aria-label="copy code" onClick={copy}
          sx={{ position: "absolute", top: 4, right: 4, opacity: 0, "&:focus-visible": { opacity: 1 } }}>
          {copied ? <Check fontSize="inherit" /> : <ContentCopy fontSize="inherit" />}
        </IconButton>
      </Tooltip>
    </Box>
  );
}

const heading = (Tag: "h1" | "h2" | "h3") =>
  function Heading({ children }: { children?: ReactNode }) {
    return <Tag id={slugify(textOf(children))} style={{ scrollMarginTop: 72 }}>{children}</Tag>;
  };

export function Markdown({ children }: { children: string }) {
  const navigate = useNavigate();
  const base = useContext(HelpLinkBase);

  const components: Components = {
    h1: heading("h1"), h2: heading("h2"), h3: heading("h3"),
    a({ href = "", children: kids }) {
      if (href.startsWith("help:")) {
        const [id, anchor] = href.slice(5).split("#");
        const to = helpLink(base, id, anchor);
        return <a href={to} onClick={(e) => { e.preventDefault(); navigate(to); }}>{kids}</a>;
      }
      if (href.startsWith("#")) {
        return (
          <a href={href} onClick={(e) => {
            e.preventDefault();
            document.getElementById(href.slice(1))?.scrollIntoView?.({ behavior: "smooth", block: "start" });
          }}>{kids}</a>
        );
      }
      const external = /^https?:\/\//i.test(href);
      return <a href={href} {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})}>{kids}</a>;
    },
    img({ src = "", alt }) {
      if (src.startsWith("asset:")) return <HelpImage id={src.slice(6)} alt={alt} />;
      return <img src={src} alt={alt} />;
    },
    pre({ children: kids }) {
      const code = Children.toArray(kids).find(isValidElement) as
        ReactElement<{ className?: string; children?: ReactNode }> | undefined;
      const widget = /language-tmf:([\w-]+)/.exec(code?.props.className ?? "");
      if (widget) return <HelpWidget name={widget[1]} arg={textOf(code?.props.children).trim()} />;
      return <CodeBlock>{kids}</CodeBlock>;
    },
  };

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
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components} urlTransform={urlTransform}>
        {children}
      </ReactMarkdown>
    </Box>
  );
}
