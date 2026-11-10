"use strict";
// A tiny flat-file "database" for local development — no setup required.
// Everything lives in data/db.json. Used automatically whenever DATABASE_URL
// isn't set; see db.js. All functions here are synchronous under the hood
// but wrapped to return promises, so route code can treat this module and
// db.postgres.js identically (`await db.getUserByEmail(...)`, etc).

const fs = require("fs");
const path = require("path");

const DB_PATH = path.join(__dirname, "..", "data", "db.json");

function readDB(){
  try{
    const raw = fs.readFileSync(DB_PATH, "utf8");
    return JSON.parse(raw);
  }catch(e){
    return { users: {}, orders: [], storeSms: [] };
  }
}

function writeDB(db){
  fs.writeFileSync(DB_PATH, JSON.stringify(db, null, 2), "utf8");
}

async function init(){ /* nothing to set up for a JSON file */ }

async function getUsers(){ return readDB().users; }
async function getUserByEmail(email){ return readDB().users[email] || null; }
async function saveUser(user){
  const db = readDB();
  db.users[user.email] = user;
  writeDB(db);
}

async function getOrders(){ return readDB().orders; }
async function getOrdersForUser(email){ return readDB().orders.filter(o=>o.user===email); }
async function addOrder(order){
  const db = readDB();
  db.orders.unshift(order);
  writeDB(db);
}

async function getStoreSms(){ return readDB().storeSms; }
async function addStoreSms(entry){
  const db = readDB();
  db.storeSms.unshift(entry);
  writeDB(db);
}

module.exports = {
  init,
  getUsers, getUserByEmail, saveUser,
  getOrders, getOrdersForUser, addOrder,
  getStoreSms, addStoreSms,
};
