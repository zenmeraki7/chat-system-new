import React, { useEffect } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import { startRealtimeBridge } from "./realtime/realtimeBridge";
import "./styles.css";

const queryClient = new QueryClient();

function RuntimeShell() {
  useEffect(() => startRealtimeBridge(), []);
  return <App />;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <RuntimeShell />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
);
