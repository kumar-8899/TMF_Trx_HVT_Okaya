import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "./App";
import { AuthProvider } from "./auth/AuthContext";
import { RunActivityProvider } from "./components/RunActivity";
import { ColorModeProvider } from "./theme/ColorMode";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ColorModeProvider>
      <BrowserRouter>
        <AuthProvider>
          <RunActivityProvider>
            <App />
          </RunActivityProvider>
        </AuthProvider>
      </BrowserRouter>
    </ColorModeProvider>
  </React.StrictMode>,
);
