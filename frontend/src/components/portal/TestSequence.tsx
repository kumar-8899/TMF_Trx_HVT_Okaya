import { Alert, Box, Typography } from "@mui/material";

/** Framework default for the User Portal's **Test Sequence** tab: a placeholder.
 *
 * The framework deliberately does NOT generate this content from the live recipe — what a
 * technician needs to read about a test (its purpose, wiring, limits' meaning, what the numbers
 * map to) is authored per application. A fork replaces this view by dropping a file under
 * `frontend/src/app/overrides/` that default-exports `{ key: "portal-test-sequence", component }`.
 * See docs/contracts/PORTAL.md "Test Sequence tab" for the authoring workflow. */
export function TestSequence() {
  return (
    <Box sx={{ maxWidth: 720 }}>
      <Alert severity="info" sx={{ mb: 2 }}>
        This application has not published a test-sequence view yet.
      </Alert>
      <Typography variant="body2" color="text.secondary">
        The Test Sequence tab is authored per application: it explains each step of this product's
        test — what is measured, how it is wired, and what the limits mean. Ask your application
        developer to add it (override key <code>portal-test-sequence</code>).
      </Typography>
    </Box>
  );
}
