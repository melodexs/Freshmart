"use strict";
const express = require("express");
const { PRODUCTS, DELIVERY_FEE } = require("../products");

const router = express.Router();

router.get("/", (req, res) => {
  res.json({ products: PRODUCTS, deliveryFee: DELIVERY_FEE });
});

module.exports = router;
