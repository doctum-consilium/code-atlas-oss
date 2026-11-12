import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { Boot } from "./Boot";
import "./style.css";

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <Boot />
    </StrictMode>,
  );
}
