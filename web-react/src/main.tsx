import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { cache } from "./lib/cache";
import { prefs } from "./lib/prefs";
import { router } from "./lib/router";
import "./styles/index.css";

// Drive always dark: the theme follows the area synchronously with each route change (before React renders it).
prefs.follow(router);
// What is on screen refetches when the tab comes back.
cache.refetchOnFocus();

const root = document.getElementById("root");
if (!root) throw new Error("#root missing from index.html");

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
