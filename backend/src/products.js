"use strict";
// Product catalog — this is the single source of truth on the server.
// The frontend fetches this list; it never trusts prices sent by the browser.

const PRODUCTS = [
  {id:"p1",name:"Local Rice",cat:"Foodstuff",emoji:"🍚",options:[
    {label:"1 cup",price:400},{label:"5 cups",price:1900},{label:"10 cups",price:3700},{label:"20 cups",price:7200}]},
  {id:"p2",name:"Semovita",cat:"Foodstuff",emoji:"🌾",options:[
    {label:"1 kg",price:1100},{label:"2 kg",price:2100},{label:"5 kg",price:5000},{label:"10 kg",price:9800}]},
  {id:"p3",name:"Garri (Ijebu)",cat:"Foodstuff",emoji:"🥣",options:[
    {label:"1 cup",price:300},{label:"5 cups",price:1400},{label:"10 cups",price:2700},{label:"20 cups",price:5200}]},
  {id:"p4",name:"Beans (Oloyin)",cat:"Foodstuff",emoji:"🫘",options:[
    {label:"1 cup",price:600},{label:"5 cups",price:2800},{label:"10 cups",price:5400}]},
  {id:"p5",name:"Palm Oil",cat:"Foodstuff",emoji:"🛢️",options:[
    {label:"1 cup",price:500},{label:"½ litre",price:1000},{label:"1 litre",price:1800},{label:"2 litres",price:3500}]},
  {id:"p6",name:"Groundnut Oil",cat:"Foodstuff",emoji:"🫗",options:[
    {label:"1 cup",price:600},{label:"½ litre",price:1150},{label:"1 litre",price:2200},{label:"2 litres",price:4300}]},
  {id:"p7",name:"Indomie Noodles",cat:"Snacks",emoji:"🍜",options:[
    {label:"Minimie (single)",price:150},{label:"Minimie (pack of 10)",price:1400},
    {label:"Superpack (single)",price:300},{label:"Superpack (pack of 5)",price:1400},
    {label:"Hungry-man (single)",price:500},{label:"Hungry-man (pack of 5)",price:2400}]},
  {id:"p8",name:"Plantain Chips",cat:"Snacks",emoji:"🍌",options:[
    {label:"1 single",price:300},{label:"3 singles",price:850},{label:"6 singles",price:1650},{label:"12 singles",price:3200}]},
  {id:"p9",name:"Chin Chin",cat:"Snacks",emoji:"🍪",options:[
    {label:"200g",price:500},{label:"500g",price:1200},{label:"1 kg",price:2300}]},
  {id:"p10",name:"Meat Pie",cat:"Snacks",emoji:"🥧",options:[
    {label:"1 single",price:500},{label:"4 singles",price:1900},{label:"6 singles",price:2800},{label:"12 singles",price:5500}]},
  {id:"p11",name:"Peak Milk",cat:"Drinks & Dairy",emoji:"🥛",options:[
    {label:"1 sachet",price:200},{label:"6 sachets",price:1150},{label:"12 sachets",price:2200},{label:"24 sachets",price:4300}]},
  {id:"p12",name:"Bottled Water",cat:"Drinks & Dairy",emoji:"💧",options:[
    {label:"1 bottle",price:150},{label:"6 bottles",price:850},{label:"12 bottles",price:1600},{label:"24 bottles",price:3100}]},
  {id:"p13",name:"Coca-Cola",cat:"Drinks & Dairy",emoji:"🥤",options:[
    {label:"1 plastic",price:450},{label:"6 plastics",price:2400},{label:"12 plastics",price:4700},{label:"24 plastics",price:9200}]},
  {id:"p14",name:"Fresh Yoghurt",cat:"Drinks & Dairy",emoji:"🧴",options:[
    {label:"250ml",price:700},{label:"500ml",price:1300},{label:"1 litre",price:2400}]},
  {id:"p15",name:"Fresh Tomatoes",cat:"Fresh Produce",emoji:"🍅",options:[
    {label:"Small basket",price:3500},{label:"Medium basket",price:6500},{label:"Large basket",price:12000}]},
  {id:"p16",name:"Onions",cat:"Fresh Produce",emoji:"🧅",options:[
    {label:"1 kg",price:1000},{label:"2 kg",price:1900},{label:"5 kg",price:4600}]},
  {id:"p17",name:"Yam Tubers",cat:"Fresh Produce",emoji:"🍠",options:[
    {label:"1 tuber",price:1600},{label:"2 tubers",price:3000},{label:"4 tubers",price:5800},{label:"6 tubers",price:8500}]},
  {id:"p18",name:"Fresh Pepper Mix",cat:"Fresh Produce",emoji:"🌶️",options:[
    {label:"250g",price:600},{label:"500g",price:1100},{label:"1 kg",price:2100}]},
  {id:"p19",name:"Dish Soap",cat:"Household",emoji:"🧴",options:[
    {label:"250ml",price:550},{label:"500ml",price:950},{label:"1 litre",price:1800}]},
  {id:"p20",name:"Toilet Rolls",cat:"Household",emoji:"🧻",options:[
    {label:"1 roll",price:250},{label:"Pack of 4",price:950},{label:"Pack of 8",price:1750},{label:"Pack of 16",price:3300}]},
  {id:"p21",name:"Detergent Powder",cat:"Household",emoji:"🧺",options:[
    {label:"1 sachet",price:150},{label:"6 sachets",price:850},{label:"12 sachets",price:1650},{label:"24 sachets",price:3200}]},
  {id:"p22",name:"Insecticide Spray",cat:"Household",emoji:"🦟",options:[
    {label:"300ml",price:1400},{label:"600ml",price:2600},{label:"1 litre",price:4200}]},
  {id:"p23",name:"Bread",cat:"Bakery",emoji:"🍞",options:[
    {label:"Small loaf",price:1000},{label:"Medium loaf",price:1600},{label:"Large loaf",price:2300},{label:"Family loaf",price:3000}]},
  {id:"p24",name:"Climax Energy Drink",cat:"Drinks & Dairy",emoji:"⚡",options:[
    {label:"1 bottle",price:400},{label:"6 bottles",price:2300},{label:"12 bottles",price:4500},{label:"24 bottles",price:8800}]},
  {id:"p25",name:"Pepsi",cat:"Drinks & Dairy",emoji:"🥤",options:[
    {label:"1 plastic",price:450},{label:"6 plastics",price:2400},{label:"12 plastics",price:4700},{label:"24 plastics",price:9200}]},
  {id:"p26",name:"Malt",cat:"Drinks & Dairy",emoji:"🍺",options:[
    {label:"1 bottle",price:500},{label:"6 bottles",price:2800},{label:"12 bottles",price:5500},{label:"24 bottles",price:10800}]},
  {id:"p27",name:"Dudu (Milky Drink)",cat:"Drinks & Dairy",emoji:"🥛",options:[
    {label:"1 bottle",price:300},{label:"6 bottles",price:1700},{label:"12 bottles",price:3300},{label:"24 bottles",price:6400}]},
  {id:"p28",name:"Perfumes",cat:"Beauty & Personal Care",emoji:"🌸",options:[
    {label:"Body spray 150ml",price:3500},{label:"Body spray 250ml",price:5000},{label:"Perfume 50ml",price:8000},{label:"Perfume 100ml",price:14000}]},
];

const DELIVERY_FEE = 800;

function findOption(productId, optionIndex){
  const p = PRODUCTS.find(x=>x.id===productId);
  if(!p) return null;
  const o = p.options[optionIndex];
  if(!o) return null;
  return {product:p, option:o};
}

module.exports = { PRODUCTS, DELIVERY_FEE, findOption };
