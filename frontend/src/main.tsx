import React from "react";
import { createRoot } from "react-dom/client";
import "./style.css";
import App from "./App";
import PWA from "./PWA";
import "./v2.css";
import "./readability.css";
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <PWA /><App />
  </React.StrictMode>,
);
