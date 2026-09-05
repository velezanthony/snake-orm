import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router";

import { router } from "~/config/router";
import "~/app.css";

const container = document.getElementById("root");
if (container === null) throw new Error("index.html is missing its #root element.");

createRoot(container).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
