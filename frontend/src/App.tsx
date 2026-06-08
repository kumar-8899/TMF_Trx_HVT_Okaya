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
import { Recipes } from "./screens/Recipes";
import { Runs } from "./screens/Runs";
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
          <Route path="/runs" element={<RequirePermission perm="TEST.RUN"><Runs /></RequirePermission>} />
          <Route path="/logs" element={<RequirePermission perm="DIAGNOSTICS.VIEW"><Logs /></RequirePermission>} />
          <Route path="/users" element={<RequirePermission perm="AUTH.MANAGE_USERS"><Users /></RequirePermission>} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
