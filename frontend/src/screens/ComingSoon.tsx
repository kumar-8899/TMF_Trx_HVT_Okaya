import { Alert, Typography } from "@mui/material";

export function ComingSoon({ name }: { name: string }) {
  return (
    <>
      <Typography variant="h5" gutterBottom>{name}</Typography>
      <Alert severity="info">This screen lands in a later frontend slice. The nav item is permission-gated.</Alert>
    </>
  );
}
