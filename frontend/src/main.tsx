import React, { useEffect } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { startRealtimeBridge } from "./realtime/realtimeBridge";
import "./styles.css";

function RuntimeShell() {
  useEffect(() => startRealtimeBridge(), []);
  return <App />;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <RuntimeShell />
    </BrowserRouter>
  </React.StrictMode>
);
