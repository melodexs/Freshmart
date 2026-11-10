"use strict";
require("dotenv").config(); // loads a local .env file if present; harmless if it's not

const path = require("path");
const express = require("express");
const cookieParser = require("cookie-parser");

const db = require("./src/db");
const { optionalAuth } = require("./src/auth");
const authRoutes = require("./src/routes/auth");
const productRoutes = require("./src/routes/products");
const orderRoutes = require("./src/routes/orders");
const storeRoutes = require("./src/routes/store");

const app = express();
const PORT = process.env.PORT || 4000;

app.use(express.json());
app.use(cookieParser());
app.use(optionalAuth); // attaches req.user when a valid session cookie is present

app.use("/api/auth", authRoutes);
app.use("/api/products", productRoutes);
app.use("/api/orders", orderRoutes);
app.use("/api/store", storeRoutes);

// Serve the frontend as static files, so the whole site runs from one
// server/port with no CORS setup needed.
const FRONTEND_DIR = path.join(__dirname, "..", "frontend");
app.use(express.static(FRONTEND_DIR));
app.get("*", (req, res, next) => {
  if(req.path.startsWith("/api/")) return next();
  res.sendFile(path.join(FRONTEND_DIR, "index.html"));
});

async function start(){
  await db.init(); // creates tables on first run when using Postgres; no-op for the file store
  app.listen(PORT, () => {
    const mode = process.env.DATABASE_URL ? "Postgres" : "local JSON file";
    console.log(`Fatoke Market backend running at http://localhost:${PORT} (data store: ${mode})`);
  });
}

start().catch(err => {
  console.error("Failed to start server:", err);
  process.exit(1);
});
