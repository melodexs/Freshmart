"use strict";
// Real Postgres-backed data layer — used automatically whenever
// DATABASE_URL is set (Render, Neon, Supabase, or any other hosted
// Postgres). Same exported functions as db.file.js, so routes never know
// or care which one is active.

const { Pool } = require("pg");

// Most hosted Postgres providers (Render, Neon, Supabase) require SSL and
// use a certificate that Node won't automatically trust, so we accept it
// without verifying the chain. Fine for this project's scale; a stricter
// setup would pin the provider's CA certificate instead.
const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  ssl: { rejectUnauthorized: false },
});

async function init(){
  await pool.query(`
    CREATE TABLE IF NOT EXISTS users (
      email      TEXT PRIMARY KEY,
      name       TEXT NOT NULL,
      phone      TEXT NOT NULL,
      pass_hash  TEXT NOT NULL
    );
  `);
  await pool.query(`
    CREATE TABLE IF NOT EXISTS orders (
      id             TEXT PRIMARY KEY,
      date           TIMESTAMPTZ NOT NULL,
      items          JSONB NOT NULL,
      subtotal       INTEGER NOT NULL,
      delivery_fee   INTEGER NOT NULL,
      total          INTEGER NOT NULL,
      address        TEXT NOT NULL,
      phone          TEXT NOT NULL,
      city           TEXT,
      pay_method     TEXT NOT NULL,
      payment_detail JSONB,
      status         TEXT NOT NULL,
      user_email     TEXT NOT NULL REFERENCES users(email)
    );
  `);
  await pool.query(`
    CREATE TABLE IF NOT EXISTS store_sms (
      id   TEXT NOT NULL,
      text TEXT NOT NULL,
      date TIMESTAMPTZ NOT NULL
    );
  `);
}

function rowToUser(row){
  if(!row) return null;
  return { name: row.name, phone: row.phone, email: row.email, passHash: row.pass_hash };
}

async function getUsers(){
  const { rows } = await pool.query(`SELECT * FROM users`);
  const out = {};
  for(const r of rows) out[r.email] = rowToUser(r);
  return out;
}

async function getUserByEmail(email){
  const { rows } = await pool.query(`SELECT * FROM users WHERE email = $1`, [email]);
  return rowToUser(rows[0]);
}

async function saveUser(user){
  await pool.query(
    `INSERT INTO users (email, name, phone, pass_hash) VALUES ($1,$2,$3,$4)
     ON CONFLICT (email) DO UPDATE SET name=$2, phone=$3, pass_hash=$4`,
    [user.email, user.name, user.phone, user.passHash]
  );
}

function rowToOrder(row){
  return {
    id: row.id,
    date: row.date.toISOString ? row.date.toISOString() : row.date,
    items: row.items,
    subtotal: row.subtotal,
    deliveryFee: row.delivery_fee,
    total: row.total,
    address: row.address,
    phone: row.phone,
    city: row.city,
    payMethod: row.pay_method,
    paymentDetail: row.payment_detail,
    status: row.status,
    user: row.user_email,
  };
}

async function getOrders(){
  const { rows } = await pool.query(`SELECT * FROM orders ORDER BY date DESC`);
  return rows.map(rowToOrder);
}

async function getOrdersForUser(email){
  const { rows } = await pool.query(
    `SELECT * FROM orders WHERE user_email = $1 ORDER BY date DESC`,
    [email]
  );
  return rows.map(rowToOrder);
}

async function addOrder(order){
  await pool.query(
    `INSERT INTO orders
       (id, date, items, subtotal, delivery_fee, total, address, phone, city, pay_method, payment_detail, status, user_email)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)`,
    [
      order.id, order.date, JSON.stringify(order.items), order.subtotal, order.deliveryFee,
      order.total, order.address, order.phone, order.city, order.payMethod,
      JSON.stringify(order.paymentDetail || {}), order.status, order.user,
    ]
  );
}

async function getStoreSms(){
  const { rows } = await pool.query(`SELECT * FROM store_sms ORDER BY date DESC`);
  return rows.map(r => ({ id: r.id, text: r.text, date: r.date.toISOString ? r.date.toISOString() : r.date }));
}

async function addStoreSms(entry){
  await pool.query(
    `INSERT INTO store_sms (id, text, date) VALUES ($1,$2,$3)`,
    [entry.id, entry.text, entry.date]
  );
}

module.exports = {
  init,
  getUsers, getUserByEmail, saveUser,
  getOrders, getOrdersForUser, addOrder,
  getStoreSms, addStoreSms,
};
