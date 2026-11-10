"use strict";
const express = require("express");
const bcrypt = require("bcryptjs");
const db = require("../db");
const { signToken, setAuthCookie, clearAuthCookie } = require("../auth");

const router = express.Router();

router.post("/signup", async (req, res) => {
  const { name, phone, email: rawEmail, password, passwordConfirm } = req.body || {};
  const email = (rawEmail || "").trim().toLowerCase();

  if(!name || !phone) return res.status(400).json({ error: "Please add your name and phone number." });
  if(!email || !password) return res.status(400).json({ error: "Please fill in email and password." });
  if(password.length < 6) return res.status(400).json({ error: "Password should be at least 6 characters." });
  if(passwordConfirm !== undefined && password !== passwordConfirm){
    return res.status(400).json({ error: "Passwords don't match. Please re-enter them." });
  }
  if(await db.getUserByEmail(email)){
    return res.status(409).json({ error: "An account with that email already exists — try signing in instead." });
  }

  const passHash = await bcrypt.hash(password, 10);
  const user = { name, phone, email, passHash };
  await db.saveUser(user);

  const token = signToken(user);
  setAuthCookie(res, token);
  res.json({ name: user.name, email: user.email });
});

router.post("/login", async (req, res) => {
  const { email: rawEmail, password } = req.body || {};
  const email = (rawEmail || "").trim().toLowerCase();
  if(!email || !password) return res.status(400).json({ error: "Please fill in email and password." });

  const user = await db.getUserByEmail(email);
  if(!user) return res.status(401).json({ error: "Email or password is incorrect." });

  const ok = await bcrypt.compare(password, user.passHash);
  if(!ok) return res.status(401).json({ error: "Email or password is incorrect." });

  const token = signToken(user);
  setAuthCookie(res, token);
  res.json({ name: user.name, email: user.email });
});

router.post("/logout", (req, res) => {
  clearAuthCookie(res);
  res.json({ ok: true });
});

// Who's currently signed in, based on the cookie (used to restore session on page load).
router.get("/me", (req, res) => {
  if(!req.user) return res.status(401).json({ error: "Not signed in." });
  res.json({ name: req.user.name, email: req.user.email });
});

// Safe public lookup used only to greet a returning user by name before
// they type their password (the "Welcome back" quick sign-in screen).
// Deliberately returns name only — never the password hash.
router.get("/lookup/:email", async (req, res) => {
  const email = (req.params.email || "").trim().toLowerCase();
  const user = await db.getUserByEmail(email);
  if(!user) return res.status(404).json({ error: "No account with that email." });
  res.json({ name: user.name, email: user.email });
});

module.exports = router;
