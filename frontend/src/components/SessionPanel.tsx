import { Logout } from "@mui/icons-material";
import { Avatar, Box, Chip, Divider, IconButton, Stack, Tooltip, Typography } from "@mui/material";

import { useAuth } from "../auth/AuthContext";

export function SessionPanel() {
  const { principal, logout } = useAuth();
  if (!principal) return null;
  const initials = principal.username.slice(0, 2).toUpperCase();
  return (
    <Stack direction="row" spacing={1} alignItems="center">
      <Divider orientation="vertical" flexItem sx={{ mx: 0.5, display: { xs: "none", sm: "block" } }} />
      <Avatar sx={{ width: 28, height: 28, fontSize: 12, bgcolor: "primary.dark", color: "primary.contrastText" }}>
        {initials}
      </Avatar>
      <Box sx={{ display: { xs: "none", sm: "block" }, lineHeight: 1.1 }}>
        <Typography variant="body2" fontWeight={600}>{principal.username}</Typography>
        <Chip size="small" label={principal.role} variant="outlined"
          sx={{ height: 16, fontSize: 10, "& .MuiChip-label": { px: 0.75 } }} />
      </Box>
      <Tooltip title="Log out">
        <IconButton size="small" onClick={logout} aria-label="logout">
          <Logout fontSize="small" />
        </IconButton>
      </Tooltip>
    </Stack>
  );
}
