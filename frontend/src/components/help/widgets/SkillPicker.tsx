/** `tmf:skill-picker` — "which skill do I use?" as a two-question chooser. Skill names/descriptions
 * come from the generated facts (so a new skill shows up automatically); the routing is static. */
import { Alert, Box, Button, Stack, Typography } from "@mui/material";
import { useState } from "react";

import { useFacts } from "./facts";

interface Node { q: string; options: { label: string; next?: string; skill?: string }[] }

export const TREE: Record<string, Node> = {
  start: {
    q: "What are you doing?",
    options: [
      { label: "Starting a brand-new application", next: "similar" },
      { label: "Working inside an application that already exists", next: "existing" },
    ],
  },
  similar: {
    q: "Is there an existing app that is already close to what you need?",
    options: [
      { label: "Yes — same/overlapping instruments or a similar test sequence", skill: "clone-test-app" },
      { label: "No — nothing comparable", skill: "new-test-app" },
    ],
  },
  existing: {
    q: "What do you want to add?",
    options: [
      { label: "A test or test sequence (end to end)", skill: "add-bench-test" },
      { label: "A new kind of test step (product-specific logic)", skill: "test-step-authoring" },
      { label: "A driver for an instrument that has none", skill: "create-instrument-library" },
      { label: "I have a spreadsheet describing the system's I/O", skill: "system-blueprint" },
    ],
  },
};

export function SkillPickerWidget() {
  const { facts } = useFacts();
  const [path, setPath] = useState<string[]>(["start"]);
  const [skill, setSkill] = useState<string | null>(null);
  const node = TREE[path[path.length - 1]];
  const info = skill ? facts?.skills.find((s) => s.name === skill) : null;
  const reset = () => { setPath(["start"]); setSkill(null); };

  return (
    <Box sx={{ my: 2, p: 2, border: "1px solid", borderColor: "divider", borderRadius: 1 }}>
      <Typography variant="subtitle2" sx={{ mb: 1 }}>Which skill?</Typography>
      {skill ? (
        <Alert severity="success" action={<Button size="small" onClick={reset}>Start over</Button>}>
          Use <strong>{skill}</strong> — say what you want to Claude Code, or type <code>/{skill}</code>.
          {info && <Typography variant="caption" component="div" sx={{ mt: 0.5 }}>{info.description}</Typography>}
        </Alert>
      ) : (
        <>
          <Typography variant="body2" sx={{ mb: 1 }}>{node.q}</Typography>
          <Stack spacing={1} alignItems="flex-start">
            {node.options.map((o) => (
              <Button key={o.label} size="small" variant="outlined"
                onClick={() => (o.skill ? setSkill(o.skill) : setPath([...path, o.next!]))}>{o.label}</Button>
            ))}
            {path.length > 1 && <Button size="small" onClick={reset}>← Back to start</Button>}
          </Stack>
        </>
      )}
    </Box>
  );
}
