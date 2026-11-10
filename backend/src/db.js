"use strict";
// Data layer. Two modes, same exported functions either way:
//
//  - DATABASE_URL set (e.g. on Render, or any hosted Postgres like Neon/
//    Supabase): uses real Postgres, and data survives restarts/redeploys.
//  - DATABASE_URL not set (plain local development): falls back to the
//    flat JSON file at backend/data/db.json, so `npm install && npm start`
//    still works with zero setup.
//
// Every route only ever calls the functions exported at the bottom of this
// file, so switching modes (or swapping Postgres for another database later)
// never requires touching routes/*.js.

const USE_POSTGRES = !!process.env.DATABASE_URL;

module.exports = USE_POSTGRES ? require("./db.postgres") : require("./db.file");
