"use strict";
const jwt = require("jsonwebtoken");

const JWT_SECRET = process.env.JWT_SECRET || "dev-secret-change-me-before-real-use";
const COOKIE_NAME = "fm_token";
const TOKEN_TTL = "30d";

function signToken(user){
  return jwt.sign({ email: user.email, name: user.name }, JWT_SECRET, { expiresIn: TOKEN_TTL });
}

function setAuthCookie(res, token){
  res.cookie(COOKIE_NAME, token, {
    httpOnly: true,
    sameSite: "lax",
    // secure:true should be added once this runs behind HTTPS in production
    maxAge: 30 * 24 * 60 * 60 * 1000,
  });
}

function clearAuthCookie(res){
  res.clearCookie(COOKIE_NAME);
}

// Attaches req.user if a valid cookie is present; never blocks the request.
function optionalAuth(req, res, next){
  const token = req.cookies && req.cookies[COOKIE_NAME];
  if(token){
    try{
      req.user = jwt.verify(token, JWT_SECRET);
    }catch(e){
      req.user = null;
    }
  }
  next();
}

// Blocks the request with 401 if there's no valid session.
function requireAuth(req, res, next){
  if(!req.user){
    return res.status(401).json({ error: "Please sign in to continue." });
  }
  next();
}

module.exports = { signToken, setAuthCookie, clearAuthCookie, optionalAuth, requireAuth, COOKIE_NAME };
