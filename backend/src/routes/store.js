"use strict";
const express = require("express");
const db = require("../db");

const router = express.Router();

// NOTE: this is intentionally open with no auth check in this demo, so the
// footer link can show it easily. In a real deployment this must be
// restricted to store staff (an admin login, a role check, etc.) — it's
// the store's own order feed, not something customers should see.
router.get("/notifications", async (req, res) => {
  res.json({ notifications: await db.getStoreSms() });
});

module.exports = router;
