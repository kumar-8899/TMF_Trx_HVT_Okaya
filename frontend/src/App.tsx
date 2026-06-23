import { Box, CircularProgress } from "@mui/material";
import { Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";

import { useAuth } from "./auth/AuthContext";
import { RequirePermission } from "./auth/RequirePermission";
import { Layout } from "./components/Layout";
import { ChangePassword } from "./screens/ChangePassword";
import { Daq } from "./screens/Daq";
import { Dashboard } from "./screens/Dashboard";
import { Logs } from "./screens/Logs";
import { Login } from "./screens/Login";
import { RecipeDetail } from "./screens/RecipeDetail";
import { RecipeEditor } from "./screens/RecipeEditor";
import { Analytics } from "./screens/Analytics";
import { ConfigInstruments } from "./screens/config/Instruments";
import { ConfigMes } from "./screens/config/Mes";
import { ConfigBarcode, ConfigShift } from "./screens/config/Placeholder";
import { Diagnostics } from "./screens/Diagnostics";
import { Health } from "./screens/Health";
import { Help } from "./screens/Help";
import { Maintenance } from "./screens/Maintenance";
import { Permissions } from "./screens/Permissions";
import { Recipes } from "./screens/Recipes";
import { Reports } from "./screens/Reports";
import { Runs } from "./screens/Runs";
import { Settings } from "./screens/Settings";
import { Users } from "./screens/Users";

function Protected() {
  const { principal, loading, mustChangePassword } = useAuth();
  const loc = useLocation();
  if (loading) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", mt: 10 }}>
        <CircularProgress />
      </Box>
    );
  }
  if (!principal) return <Navigate to="/login" replace />;
  if (mustChangePassword && loc.pathname !== "/change-password") {
    return <Navigate to="/change-password" replace />;
  }
  return <Outlet />;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<Protected />}>
        <Route path="/change-password" element={<ChangePassword />} />
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/recipes" element={<RequirePermission perm="RECIPE.VIEW"><Recipes /></RequirePermission>} />
          <Route path="/recipes/new" element={<RequirePermission perm="RECIPE.EDIT"><RecipeEditor /></RequirePermission>} />
          <Route path="/recipes/:id" element={<RequirePermission perm="RECIPE.VIEW"><RecipeDetail /></RequirePermission>} />
          <Route path="/recipes/:id/edit" element={<RequirePermission perm="RECIPE.EDIT"><RecipeEditor /></RequirePermission>} />
          <Route path="/daq" element={<Daq />} />
          <Route path="/reports" element={<RequirePermission perm="REPORT.VIEW"><Reports /></RequirePermission>} />
          <Route path="/analytics" element={<RequirePermission perm="REPORT.VIEW"><Analytics /></RequirePermission>} />
          <Route path="/health" element={<RequirePermission perm="HEALTH.VIEW"><Health /></RequirePermission>} />
          <Route path="/config/instruments" element={<RequirePermission perm="CONFIG.VIEW"><ConfigInstruments /></RequirePermission>} />
          <Route path="/config/barcode" element={<RequirePermission perm="CONFIG.VIEW"><ConfigBarcode /></RequirePermission>} />
          <Route path="/config/shift" element={<RequirePermission perm="CONFIG.VIEW"><ConfigShift /></RequirePermission>} />
          <Route path="/config/mes" element={<RequirePermission perm="CONFIG.VIEW"><ConfigMes /></RequirePermission>} />
          <Route path="/maintenance" element={<RequirePermission perm="HEALTH.MAINTENANCE"><Maintenance /></RequirePermission>} />
          <Route path="/diagnostics" element={<RequirePermission perm="DIAGNOSTICS.VIEW"><Diagnostics /></RequirePermission>} />
          <Route path="/logs" element={<RequirePermission perm="DIAGNOSTICS.VIEW"><Logs /></RequirePermission>} />
          <Route path="/users" element={<RequirePermission perm="AUTH.MANAGE_USERS"><Users /></RequirePermission>} />
          <Route path="/permissions" element={<RequirePermission perm="AUTH.MANAGE_ROLES"><Permissions /></RequirePermission>} />
          <Route path="/settings" element={<RequirePermission perm="SYSTEM.RESET_DATA"><Settings /></RequirePermission>} />
          <Route path="/help" element={<RequirePermission perm="HELP.VIEW"><Help /></RequirePermission>} />
        </Route>
        {/* Operator testing window — same AppBar, no side-menu drawer. */}
        <Route element={<Layout hideNav />}>
          <Route path="/runs" element={<RequirePermission perm="TEST.RUN"><Runs /></RequirePermission>} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
