
(function(){
"use strict";

// ---------- data ----------
// The product catalog now lives on the server (backend/src/products.js) and
// is fetched once at startup — see loadCatalog() in the init section below.
// This keeps the frontend from ever inventing its own prices.
let PRODUCTS = [];
let CATEGORIES = ["All"];
const BANKS = ["GTBank","Access Bank","Zenith Bank","UBA","First Bank","Fidelity Bank","Union Bank","Sterling Bank",
  "Opay","Palmpay","Kuda Bank","Moniepoint MFB","LAPO Microfinance Bank","AB Microfinance Bank","Accion MFB","VFD Microfinance Bank"];
const USSD_CODES = {"GTBank":"*737#","Access Bank":"*901#","Zenith Bank":"*966#","UBA":"*919#","First Bank":"*894#"};
let DELIVERY_FEE = 800; // overwritten with the server's real figure once the catalog loads
const money = n => "₦" + n.toLocaleString("en-NG");

// ---------- state (cart stays client-side only; accounts and orders live on the server) ----------
let cart = {};           // {"productId|optionIndex": {qty, note}}
let currentUser = null;  // {name, email} — mirrors the server session cookie
let activeCat = "All";
let selectedPay = null;
let payTab = "card";
let selectedBank = null;

// ---------- tiny fetch helpers ----------
// Same-origin requests automatically carry the session cookie; "same-origin"
// is set explicitly here just to be clear about that.
async function apiGet(path){
  const r = await fetch(path, { credentials: "same-origin" });
  const data = await r.json().catch(()=>({}));
  if(!r.ok) throw data;
  return data;
}
async function apiPost(path, body){
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(body || {}),
  });
  const data = await r.json().catch(()=>({}));
  if(!r.ok) throw data;
  return data;
}

// ---------- render: categories & products ----------
const catNav = document.getElementById("catNav");
function buildCatNav(){
  catNav.innerHTML = "";
  CATEGORIES.forEach(cat=>{
    const b = document.createElement("button");
    b.textContent = cat;
    if(cat===activeCat) b.classList.add("active");
    b.onclick = ()=>{ activeCat=cat; renderCatNav(); renderProducts(); };
    catNav.appendChild(b);
  });
}
function renderCatNav(){
  Array.from(catNav.children).forEach(b=>b.classList.toggle("active", b.textContent===activeCat));
  document.getElementById("sectionHeading").textContent = activeCat==="All" ? "All products" : activeCat;
}

const grid = document.getElementById("productGrid");
let sel = {}; // chosen option index per product
function renderProducts(){
  const q = document.getElementById("searchInput").value.trim().toLowerCase();
  grid.innerHTML = "";
  PRODUCTS.filter(p=> (activeCat==="All"||p.cat===activeCat) && p.name.toLowerCase().includes(q))
    .forEach(p=>{
      const idx = sel[p.id]||0, o = p.options[idx], key = p.id+"|"+idx;
      const multi = p.options.length>1;
      const card = document.createElement("div");
      card.className="card";
      card.innerHTML = `<div class="thumb">${p.emoji}</div><h3>${p.name}</h3>` +
        (multi
          ? `<select class="opt-select" aria-label="Choose size for ${p.name}">${p.options.map((op,i)=>`<option value="${i}"${i===idx?" selected":""}>${op.label}</option>`).join("")}</select>`
          : `<div class="unit">${o.label}</div>`) +
        `<div class="row"><div class="price">${money(o.price)}</div></div><div class="qtyArea"></div>`;
      if(multi) card.querySelector(".opt-select").onchange = e=>{ sel[p.id]=+e.target.value; renderProducts(); };
      renderQtyArea(card.querySelector(".qtyArea"), key, (cart[key]&&cart[key].qty)||0);
      grid.appendChild(card);
    });
}
function renderQtyArea(el, key, qty){
  if(qty>0){
    const note = (cart[key]&&cart[key].note)||"";
    el.innerHTML = `<div class="stepper"><button data-act="dec">−</button><span>${qty}</span><button data-act="inc">+</button></div>
      <input class="note-input" placeholder="Any specifics? e.g. scent, brand, ripeness" value="${note.replace(/"/g,'&quot;')}">`;
    el.querySelector('[data-act="dec"]').onclick=()=>changeQty(key,-1);
    el.querySelector('[data-act="inc"]').onclick=()=>changeQty(key,1);
    el.querySelector('.note-input').oninput=e=>setNote(key,e.target.value);
  } else {
    el.innerHTML = `<button class="add-btn">Add to cart</button>`;
    el.querySelector("button").onclick=()=>changeQty(key,1);
  }
}
function changeQty(key, delta){
  const cur = cart[key] || {qty:0, note:""};
  const next = cur.qty + delta;
  if(next<=0) delete cart[key]; else cart[key] = {qty:next, note:cur.note};
  renderProducts(); renderCartCount(); renderCartDrawer(); renderReview();
}
function setNote(key, note){
  if(cart[key]) cart[key].note = note;
}
document.getElementById("searchInput").addEventListener("input", renderProducts);

// ---------- cart drawer ----------
function renderCartCount(){
  const distinctItems = Object.keys(cart).length;
  document.getElementById("cartCount").textContent = distinctItems;
  document.getElementById("fabCartCount").textContent = distinctItems;
}
function cartLines(){
  return Object.entries(cart).map(([key,entry])=>{
    const [id,i] = key.split("|");
    const p = PRODUCTS.find(x=>x.id===id), o = p.options[+i];
    return {key, p, o, qty:entry.qty, note:entry.note||"", unitPrice:o.price, subtotal:o.price*entry.qty};
  });
}
function renderCartDrawer(){
  const body = document.getElementById("cartBody");
  const foot = document.getElementById("cartFoot");
  const lines = cartLines();
  if(lines.length===0){
    body.innerHTML = `<div class="empty-note">Your cart is empty.<br>Browse products and add a few things.</div>`;
    foot.innerHTML = "";
    return;
  }
  body.innerHTML = lines.map(l=>`
    <div class="line-item">
      <div style="font-size:1.4rem;">${l.p.emoji}</div>
      <div class="grow">
        <div class="name">${l.p.name}</div>
        <div class="sub">${l.o.label} · ${l.qty} × ${money(l.unitPrice)}</div>
        ${l.note?`<div class="sub" style="font-style:italic;">"${l.note.replace(/</g,"&lt;")}"</div>`:""}
      </div>
      <div style="text-align:right;">
        <div style="font-weight:600;font-size:.85rem;">${money(l.subtotal)}</div>
        <button class="remove" data-id="${l.key}">Remove</button>
      </div>
    </div>
  `).join("");
  body.querySelectorAll(".remove").forEach(btn=>{
    btn.onclick = ()=>{ delete cart[btn.dataset.id]; renderProducts(); renderCartCount(); renderCartDrawer(); };
  });
  const subtotal = lines.reduce((a,l)=>a+l.subtotal,0);
  const total = subtotal + DELIVERY_FEE;
  foot.innerHTML = `
    <div class="totals-row"><span>Subtotal</span><span>${money(subtotal)}</span></div>
    <div class="totals-row"><span>Delivery fee</span><span>${money(DELIVERY_FEE)}</span></div>
    <div class="totals-row grand"><span>Total</span><span>${money(total)}</span></div>
    <button class="btn-primary" id="goCheckout">Checkout</button>
  `;
  document.getElementById("goCheckout").onclick = openCheckout;
}
function openCart(){ document.getElementById("cartOverlay").classList.add("show"); document.getElementById("cartDrawer").classList.add("show"); }
function closeCartFn(){ document.getElementById("cartOverlay").classList.remove("show"); document.getElementById("cartDrawer").classList.remove("show"); }
document.getElementById("cartBtn").onclick = openCart;
document.getElementById("cartFab").onclick = openCart;

// fade the floating cart out near the top of the page, where the header cart
// button is already easy to reach; reappear once the page is scrolled down.
// (the header is sticky, so a plain visibility check would always say "visible" —
// scroll position is the real signal for "near the top" here.)
(function(){
  const fab = document.getElementById("cartFab");
  const NEAR_TOP_PX = 160;
  function updateFabVisibility(){
    fab.classList.toggle("faded", window.scrollY < NEAR_TOP_PX);
  }
  window.addEventListener("scroll", updateFabVisibility, {passive:true});
  updateFabVisibility();
})();
document.getElementById("closeCart").onclick = closeCartFn;
document.getElementById("cartOverlay").onclick = closeCartFn;

// ---------- remembering the last signed-in email, for quick sign-in ----------
function getLastEmail(){ try{ return localStorage.getItem("fm_last_email")||""; }catch(e){ return ""; } }
function setLastEmail(email){ try{ localStorage.setItem("fm_last_email", email); }catch(e){} }
function clearLastEmail(){ try{ localStorage.removeItem("fm_last_email"); }catch(e){} }

// ---------- sign in ----------
const authOverlay = document.getElementById("authOverlay");
async function openAuth(){
  authOverlay.classList.add("show");
  document.getElementById("authMsg").innerHTML = "";
  const email = getLastEmail();
  let user = null;
  if(email){
    try{ user = await apiGet("/api/auth/lookup/" + encodeURIComponent(email)); }
    catch(e){ user = null; }
  }
  if(user){
    document.getElementById("quickSignin").style.display = "block";
    document.getElementById("fullAuthFields").style.display = "none";
    document.getElementById("quickSigninName").textContent = `Welcome back, ${user.name.split(" ")[0]}! Sign in as ${user.email}.`;
    document.getElementById("quickPass").value = "";
  } else {
    document.getElementById("quickSignin").style.display = "none";
    document.getElementById("fullAuthFields").style.display = "block";
    document.getElementById("authEmail").value = "";
    document.getElementById("authPass").value = "";
  }
}
function closeAuthFn(){ authOverlay.classList.remove("show"); document.getElementById("authMsg").innerHTML=""; }
document.getElementById("closeAuth").onclick = closeAuthFn;
authOverlay.onclick = e=>{ if(e.target===authOverlay) closeAuthFn(); };

function showAuthMsg(text,type){
  document.getElementById("authMsg").innerHTML = `<div class="msg ${type}">${text}</div>`;
}
document.getElementById("notYouBtn").onclick = ()=>{
  document.getElementById("quickSignin").style.display = "none";
  document.getElementById("fullAuthFields").style.display = "block";
  document.getElementById("authEmail").value = "";
  document.getElementById("authPass").value = "";
};
document.getElementById("quickSigninBtn").onclick = async ()=>{
  const email = getLastEmail();
  const pass = document.getElementById("quickPass").value;
  if(!pass){ showAuthMsg("Please enter your password.","error"); return; }
  try{
    const u = await apiPost("/api/auth/login", { email, password: pass });
    currentUser = { name: u.name, email: u.email };
    setLastEmail(u.email);
    afterAuthSuccess();
  }catch(err){
    showAuthMsg(err.error || "Incorrect password.", "error");
  }
};
document.getElementById("authSubmit").onclick = async ()=>{
  const email = document.getElementById("authEmail").value.trim().toLowerCase();
  const pass = document.getElementById("authPass").value;
  if(!email || !pass){ showAuthMsg("Please fill in email and password.","error"); return; }
  try{
    const u = await apiPost("/api/auth/login", { email, password: pass });
    currentUser = { name: u.name, email: u.email };
    setLastEmail(u.email);
    afterAuthSuccess();
  }catch(err){
    showAuthMsg(err.error || "Email or password is incorrect.", "error");
  }
};

// ---------- create account ----------
const signupOverlay = document.getElementById("signupOverlay");
function openSignup(){
  signupOverlay.classList.add("show");
  document.getElementById("signupMsg").innerHTML = "";
  ["suName","suPhone","suEmail","suPass","suPassConfirm"].forEach(id=>document.getElementById(id).value="");
}
function closeSignupFn(){ signupOverlay.classList.remove("show"); document.getElementById("signupMsg").innerHTML=""; }
document.getElementById("createAcctBtn").onclick = openSignup;
document.getElementById("closeSignup").onclick = closeSignupFn;
signupOverlay.onclick = e=>{ if(e.target===signupOverlay) closeSignupFn(); };
function showSignupMsg(text,type){
  document.getElementById("signupMsg").innerHTML = `<div class="msg ${type}">${text}</div>`;
}
document.getElementById("signupSubmit").onclick = async ()=>{
  const name = document.getElementById("suName").value.trim();
  const phone = document.getElementById("suPhone").value.trim();
  const email = document.getElementById("suEmail").value.trim().toLowerCase();
  const pass = document.getElementById("suPass").value;
  const passConfirm = document.getElementById("suPassConfirm").value;
  if(!name || !phone){ showSignupMsg("Please add your name and phone number.","error"); return; }
  if(!email || !pass){ showSignupMsg("Please fill in email and password.","error"); return; }
  if(pass.length<6){ showSignupMsg("Password should be at least 6 characters.","error"); return; }
  if(pass!==passConfirm){ showSignupMsg("Passwords don't match. Please re-enter them.","error"); return; }
  try{
    const u = await apiPost("/api/auth/signup", { name, phone, email, password: pass, passwordConfirm: passConfirm });
    currentUser = { name: u.name, email: u.email };
    setLastEmail(u.email);
    closeSignupFn();
    document.getElementById("accountLabel").textContent = currentUser.name.split(" ")[0];
    document.getElementById("logoutBtn").style.display = "flex";
    document.getElementById("createAcctBtn").style.display = "none";
  }catch(err){
    showSignupMsg(err.error || "Something went wrong creating your account.", "error");
  }
};

function showSuccessToast(text){
  const toast = document.getElementById("successToast");
  toast.textContent = "✅ " + text;
  toast.style.display = "block";
  clearTimeout(showSuccessToast._t);
  showSuccessToast._t = setTimeout(()=>{ toast.style.display = "none"; }, 2600);
}
function afterAuthSuccess(){
  closeAuthFn();
  showSuccessToast("Login successful. Welcome back, " + currentUser.name.split(" ")[0] + "!");
  document.getElementById("accountLabel").textContent = currentUser.name.split(" ")[0];
  document.getElementById("logoutBtn").style.display = "flex";
  document.getElementById("createAcctBtn").style.display = "none";
}
function signOut(){
  apiPost("/api/auth/logout", {}).catch(()=>{}); // best-effort; UI signs out either way
  currentUser = null;
  document.getElementById("accountLabel").textContent = "Sign in";
  document.getElementById("logoutBtn").style.display = "none";
  document.getElementById("createAcctBtn").style.display = "flex";
  ["confirmOverlay","ordersOverlay","checkoutOverlay"].forEach(id=>document.getElementById(id).classList.remove("show"));
  closeCartFn();
}
document.getElementById("accountBtn").onclick = ()=>{
  if(currentUser){ document.getElementById("ordersBtn").click(); } else { openAuth(); }
};
document.getElementById("logoutBtn").onclick = signOut;
document.getElementById("confirmLogout").onclick = signOut;
document.getElementById("ordersLogout").onclick = signOut;

// ---------- checkout ----------
const checkoutOverlay = document.getElementById("checkoutOverlay");
function openCheckout(){
  if(Object.keys(cart).length===0) return;
  if(!currentUser){ closeCartFn(); openAuth(); showAuthMsg("Sign in or create an account to check out.","ok"); return; }
  closeCartFn();
  checkoutOverlay.classList.add("show");
  setStep("review");
}
document.getElementById("closeCheckout").onclick = ()=> checkoutOverlay.classList.remove("show");
checkoutOverlay.onclick = e=>{ if(e.target===checkoutOverlay) checkoutOverlay.classList.remove("show"); };

document.getElementById("optDelivery").onclick = ()=>selectPay("delivery");
document.getElementById("optBefore").onclick = ()=>selectPay("before");
function selectPay(val){
  selectedPay = val;
  document.getElementById("optDelivery").classList.toggle("selected", val==="delivery");
  document.getElementById("optBefore").classList.toggle("selected", val==="before");
  document.getElementById("optDelivery").querySelector("input").checked = val==="delivery";
  document.getElementById("optBefore").querySelector("input").checked = val==="before";
  document.getElementById("beforePayPanel").style.display = val==="before" ? "block":"none";
  if(val==="before" && !document.getElementById("bankList").children.length) renderBankList();
}
function renderBankList(){
  const el = document.getElementById("bankList");
  el.innerHTML = BANKS.map(b=>`<button data-bank="${b}">${b}</button>`).join("");
  el.querySelectorAll("button").forEach(btn=>{
    btn.onclick = ()=>{
      selectedBank = btn.dataset.bank;
      el.querySelectorAll("button").forEach(b=>b.classList.remove("picked"));
      btn.classList.add("picked");
    };
  });
}
function setPayTab(tab){
  payTab = tab;
  document.getElementById("payTabCard").classList.toggle("active", tab==="card");
  document.getElementById("payTabTransfer").classList.toggle("active", tab==="transfer");
  document.getElementById("payTabUssd").classList.toggle("active", tab==="ussd");
  document.getElementById("payCardPanel").style.display = tab==="card"?"block":"none";
  document.getElementById("payTransferPanel").style.display = tab==="transfer"?"block":"none";
  document.getElementById("payUssdPanel").style.display = tab==="ussd"?"block":"none";
}
document.getElementById("payTabCard").onclick=()=>setPayTab("card");
document.getElementById("payTabTransfer").onclick=()=>{ setPayTab("transfer"); if(!document.getElementById("bankList").children.length) renderBankList(); };
document.getElementById("payTabUssd").onclick=()=>setPayTab("ussd");
document.getElementById("ussdBank").addEventListener("change", updateUssdNote);
function updateUssdNote(){
  const bank = document.getElementById("ussdBank").value;
  const code = USSD_CODES[bank] || "*XXX#";
  document.getElementById("ussdCodeNote").innerHTML = `You'd dial <strong>${code}</strong> on the phone linked to your ${bank} account to approve the payment.`;
}
updateUssdNote();

function setStep(step){
  document.getElementById("stepReview").style.display = step==="review" ? "block":"none";
  document.getElementById("stepPlace").style.display = step==="place" ? "block":"none";
  document.getElementById("tabReview").classList.toggle("active", step==="review");
  document.getElementById("tabPlace").classList.toggle("active", step==="place");
  document.getElementById("checkoutMsg").innerHTML = "";
  renderReview();
}
function renderReview(){
  const el = document.getElementById("stepReview");
  if(!el) return;
  const lines = cartLines();
  if(!lines.length){
    el.innerHTML = `<div class="empty-note">Your cart is empty.<br>Close this and add some items.</div>`;
    return;
  }
  const subtotal = lines.reduce((a,l)=>a+l.subtotal,0);
  el.innerHTML = lines.map(l=>`
    <div class="line-item">
      <div style="font-size:1.4rem;">${l.p.emoji}</div>
      <div class="grow">
        <div class="name">${l.p.name}</div>
        <div class="sub">${l.o.label} · ${money(l.unitPrice)} each</div>
        ${l.note?`<div class="sub" style="font-style:italic;">"${l.note.replace(/</g,"&lt;")}"</div>`:""}
        <div class="stepper" style="margin-top:6px;">
          <button data-k="${l.key}" data-d="-1" aria-label="Decrease">−</button>
          <span>${l.qty}</span>
          <button data-k="${l.key}" data-d="1" aria-label="Increase">+</button>
        </div>
      </div>
      <div style="text-align:right;">
        <div style="font-weight:600;font-size:.85rem;">${money(l.subtotal)}</div>
        <button class="remove" data-r="${l.key}">Remove</button>
      </div>
    </div>`).join("") + `
    <div style="margin-top:10px;">
      <div class="totals-row"><span>Subtotal</span><span>${money(subtotal)}</span></div>
      <div class="totals-row"><span>Delivery fee</span><span>${money(DELIVERY_FEE)}</span></div>
      <div class="totals-row grand"><span>Total</span><span>${money(subtotal+DELIVERY_FEE)}</span></div>
    </div>
    <button class="btn-primary" id="toPlace">Continue to place order</button>`;
  el.querySelectorAll("[data-d]").forEach(b=>{ b.onclick = ()=>changeQty(b.dataset.k, +b.dataset.d); });
  el.querySelectorAll("[data-r]").forEach(b=>{ b.onclick = ()=>changeQty(b.dataset.r, -((cart[b.dataset.r]&&cart[b.dataset.r].qty)||0)); });
  document.getElementById("toPlace").onclick = ()=>setStep("place");
  updatePlaceOrderLabel();
}
document.getElementById("tabReview").onclick = ()=>setStep("review");
document.getElementById("tabPlace").onclick = ()=>{ if(cartLines().length) setStep("place"); };
document.getElementById("backToReview").onclick = ()=>setStep("review");

function checkoutTotal(){
  return cartLines().reduce((a,l)=>a+l.subtotal,0) + DELIVERY_FEE;
}
function updatePlaceOrderLabel(){
  document.getElementById("placeOrderBtn").textContent = "Place order — " + money(checkoutTotal());
}
function showCoMsg(text,type){
  document.getElementById("checkoutMsg").innerHTML = `<div class="msg ${type}">${text}</div>`;
}
document.getElementById("placeOrderBtn").onclick = ()=>{
  if(!cartLines().length){ showCoMsg("Your cart is empty.","error"); return; }
  const address = document.getElementById("coAddress").value.trim();
  const phone = document.getElementById("coPhone").value.trim();
  if(!address || !phone){ showCoMsg("Please add your delivery address and phone number.","error"); return; }
  if(!selectedPay){ showCoMsg("Please choose a payment method.","error"); return; }
  let paymentDetail = {};
  if(selectedPay==="before"){
    if(payTab==="card"){
      const num = document.getElementById("cardNumber").value.trim();
      if(num.replace(/\s/g,"").length<12){ showCoMsg("Enter a card number to continue (demo — not charged).","error"); return; }
      paymentDetail = {type:"card", last4:num.slice(-4)};
    } else if(payTab==="transfer"){
      if(!selectedBank){ showCoMsg("Select the bank you'll transfer from.","error"); return; }
      paymentDetail = {type:"transfer", bank:selectedBank};
    } else {
      const bank = document.getElementById("ussdBank").value;
      paymentDetail = {type:"ussd", bank, code:USSD_CODES[bank]||"*XXX#"};
    }
  }
  if(selectedPay==="before" && payTab==="card"){
    checkoutOverlay.classList.remove("show");
    runCardPaymentFlow({address, phone}, paymentDetail);
    return;
  }
  finalizeOrder({address, phone}, paymentDetail);
};
async function finalizeOrder({address, phone}, paymentDetail){
  const items = cartLines().map(l=>{
    const [productId, optionIndex] = l.key.split("|");
    return { productId, optionIndex: Number(optionIndex), qty: l.qty, note: l.note || "" };
  });
  let order;
  try{
    const data = await apiPost("/api/orders", {
      items, address, phone,
      city: document.getElementById("coCity").value,
      payMethod: selectedPay,
      paymentDetail,
    });
    order = data.order;
  }catch(err){
    showCoMsg(err.error || "Couldn't place your order — please try again.", "error");
    checkoutOverlay.classList.add("show");
    return;
  }
  cart = {};
  renderProducts(); renderCartCount(); renderCartDrawer();
  checkoutOverlay.classList.remove("show");
  // The server already logged this order as a simulated store SMS (see
  // backend/src/routes/orders.js) — this just shows the same message as a toast.
  const itemSummary = order.items.map(i=>i.qty+"x "+i.name).join(", ");
  const payLine = order.payMethod==="before" ? "PAID (before delivery)" : "Pay on delivery";
  const text = `New order ${order.id} — ${money(order.total)}. ${itemSummary}. Deliver to: ${order.address}, ${order.city}. Customer: ${order.phone}. ${payLine}.`;
  showSmsToast(text);
  showConfirmation(order);
}
function showSmsToast(text){
  const toast = document.getElementById("smsToast");
  toast.innerHTML = `📩 <strong>SMS sent to store</strong><br>${text}`;
  toast.style.display = "block";
  clearTimeout(showSmsToast._t);
  showSmsToast._t = setTimeout(()=>{ toast.style.display = "none"; }, 6000);
}
document.getElementById("storeInboxBtn").onclick = async ()=>{
  const el = document.getElementById("storeInboxList");
  el.innerHTML = `<div class="empty-note">Loading…</div>`;
  document.getElementById("storeInboxOverlay").classList.add("show");
  let list = [];
  try{ list = (await apiGet("/api/store/notifications")).notifications; }catch(e){ /* show empty state below */ }
  el.innerHTML = list.length===0
    ? `<div class="empty-note">No orders yet — this fills up as orders come in.</div>`
    : list.map(m=>`
        <div class="order-hist-item">
          <div style="opacity:.7;font-size:.78rem;">${new Date(m.date).toLocaleString()}</div>
          <div style="margin-top:4px;">${m.text}</div>
        </div>`).join("");
};
document.getElementById("closeStoreInbox").onclick = ()=> document.getElementById("storeInboxOverlay").classList.remove("show");
document.getElementById("storeInboxOverlay").onclick = e=>{ if(e.target===document.getElementById("storeInboxOverlay")) document.getElementById("storeInboxOverlay").classList.remove("show"); };

// ---------- simulated card payment flow ----------
const BANK_NAMES_FOR_CARD = ["GTBank","Access Bank","Zenith Bank","UBA","First Bank"];
function bankForCard(cardNumber){
  let sum = 0; for(const ch of cardNumber) sum += ch.charCodeAt(0);
  return BANK_NAMES_FOR_CARD[sum % BANK_NAMES_FOR_CARD.length];
}
function runCardPaymentFlow(orderInfo, paymentDetail){
  const processingOverlay = document.getElementById("processingOverlay");
  const modal = document.getElementById("processingModal");
  const bank = bankForCard(document.getElementById("cardNumber").value);
  const amount = checkoutTotal();
  const maskedPhone = orderInfo.phone.length>=4 ? "*******"+orderInfo.phone.slice(-4) : orderInfo.phone;

  processingOverlay.classList.add("show");
  modal.innerHTML = `
    <div class="spinner"></div>
    <h2 style="text-align:center;">Connecting to your bank…</h2>
    <p style="text-align:center;font-size:.85rem;opacity:.7;">Verifying your card details, please wait.</p>`;

  setTimeout(()=>{
    modal.innerHTML = `
      <h2>Bank connected</h2>
      <div class="bank-badge"><span class="check">✅</span><div>
        <div style="font-weight:600;">${bank}</div>
        <div style="font-size:.8rem;opacity:.75;">Card ending ${document.getElementById("cardNumber").value.replace(/\s/g,"").slice(-4)} — connection successful.</div>
      </div></div>
      <div class="field"><label>Amount to pay</label><input id="payAmountInput" value="${amount}"></div>
      <div class="small-note">This is the total for your order. You can adjust it here only to match a demo scenario — in a real deployment the amount is fixed by your order and cannot be edited.</div>
      <button class="btn-primary" id="confirmAmountBtn">Confirm & Continue</button>
      <button class="btn-ghost" id="cancelCardPay">Cancel payment</button>`;
    document.getElementById("cancelCardPay").onclick = ()=>{ processingOverlay.classList.remove("show"); checkoutOverlay.classList.add("show"); };
    document.getElementById("confirmAmountBtn").onclick = ()=>{
      const entered = Number(document.getElementById("payAmountInput").value);
      if(!entered || entered<=0){ return; }
      showOtpStep(bank, maskedPhone, orderInfo, paymentDetail);
    };
  }, 1600);
}
function showOtpStep(bank, maskedPhone, orderInfo, paymentDetail){
  const processingOverlay = document.getElementById("processingOverlay");
  const modal = document.getElementById("processingModal");
  modal.innerHTML = `
    <h2>Enter OTP</h2>
    <p style="font-size:.88rem;">${bank} sent a one-time code by SMS to the phone number registered on your account (${maskedPhone}).</p>
    <div class="otp-boxes">
      <input maxlength="1" inputmode="numeric"><input maxlength="1" inputmode="numeric"><input maxlength="1" inputmode="numeric">
      <input maxlength="1" inputmode="numeric"><input maxlength="1" inputmode="numeric"><input maxlength="1" inputmode="numeric">
    </div>
    <div class="small-note">Demo mode — no real SMS is sent. Enter any 6 digits to continue.</div>
    <div id="otpMsg"></div>
    <button class="btn-primary" id="verifyOtpBtn">Verify & Pay</button>
    <button class="btn-ghost" id="cancelOtp">Cancel payment</button>`;
  const boxes = Array.from(modal.querySelectorAll(".otp-boxes input"));
  boxes.forEach((box,i)=>{
    box.oninput = ()=>{
      box.value = box.value.replace(/\D/g,"").slice(0,1);
      if(box.value && boxes[i+1]) boxes[i+1].focus();
    };
    box.onkeydown = e=>{ if(e.key==="Backspace" && !box.value && boxes[i-1]) boxes[i-1].focus(); };
  });
  boxes[0].focus();
  document.getElementById("cancelOtp").onclick = ()=>{ processingOverlay.classList.remove("show"); checkoutOverlay.classList.add("show"); };
  document.getElementById("verifyOtpBtn").onclick = ()=>{
    const code = boxes.map(b=>b.value).join("");
    if(code.length<6){
      document.getElementById("otpMsg").innerHTML = `<div class="msg error">Enter all 6 digits.</div>`;
      return;
    }
    modal.innerHTML = `
      <div class="spinner"></div>
      <h2 style="text-align:center;">Confirming payment…</h2>`;
    setTimeout(()=>{
      processingOverlay.classList.remove("show");
      finalizeOrder(orderInfo, paymentDetail);
    }, 1100);
  };
}
function showConfirmation(order){
  const payLine = order.payMethod==="before"
    ? `Paid ahead via ${order.paymentDetail.type==="card"?"card ending "+order.paymentDetail.last4 : order.paymentDetail.type==="transfer"?"transfer from "+order.paymentDetail.bank : "USSD via "+order.paymentDetail.bank} (simulated).`
    : "You'll pay the rider on delivery.";
  document.getElementById("confirmText").innerHTML =
    `Order <strong>${order.id}</strong> for ${money(order.total)} was placed.<br>${payLine}`;
  document.getElementById("confirmOverlay").classList.add("show");
}
document.getElementById("confirmClose").onclick = ()=> document.getElementById("confirmOverlay").classList.remove("show");

// ---------- order history ----------
const ordersOverlay = document.getElementById("ordersOverlay");
document.getElementById("ordersBtn").onclick = async ()=>{
  if(!currentUser){ openAuth(); showAuthMsg("Sign in to see your past orders.","ok"); return; }
  const list = document.getElementById("ordersList");
  list.innerHTML = `<div class="empty-note">Loading…</div>`;
  ordersOverlay.classList.add("show");
  let mine = [];
  try{ mine = (await apiGet("/api/orders/mine")).orders; }catch(e){ /* show empty state below */ }
  list.innerHTML = mine.length===0
    ? `<div class="empty-note">No orders yet. Your first one will show up here.</div>`
    : mine.map(o=>`
        <div class="order-hist-item">
          <div style="display:flex;justify-content:space-between;font-weight:600;">
            <span>${o.id}</span><span>${money(o.total)}</span>
          </div>
          <div style="opacity:.7;font-size:.8rem;">${new Date(o.date).toLocaleString()}</div>
          <div style="margin-top:4px;">${o.items.map(i=>i.qty+"× "+i.name+(i.note?" — \""+i.note.replace(/</g,"&lt;")+"\"":"")).join(", ")}</div>
          ${o.note?`<div style="margin-top:4px;">Note: ${o.note.replace(/</g,"&lt;")}</div>`:""}<div style="margin-top:4px;opacity:.8;">${o.status}</div>
        </div>
      `).join("");
};
document.getElementById("closeOrders").onclick = ()=> ordersOverlay.classList.remove("show");
ordersOverlay.onclick = e=>{ if(e.target===ordersOverlay) ordersOverlay.classList.remove("show"); };

// ---------- init ----------
async function init(){
  // 1. Load the product catalog from the server.
  try{
    const data = await apiGet("/api/products");
    PRODUCTS = data.products;
    PRODUCTS.forEach(p=>{ if(!p.options) p.options=[{label:p.unit,price:p.price}]; });
    DELIVERY_FEE = data.deliveryFee;
  }catch(e){
    document.getElementById("productGrid").innerHTML =
      `<div class="empty-note">Couldn't load the product list. Is the backend server running?</div>`;
  }
  CATEGORIES = ["All", ...Array.from(new Set(PRODUCTS.map(p=>p.cat)))];
  buildCatNav();

  // 2. Restore the session from the cookie, if there is one.
  try{
    const me = await apiGet("/api/auth/me");
    currentUser = { name: me.name, email: me.email };
    document.getElementById("accountLabel").textContent = me.name.split(" ")[0];
    document.getElementById("logoutBtn").style.display = "flex";
    document.getElementById("createAcctBtn").style.display = "none";
  }catch(e){
    // not signed in — that's fine, the header already defaults to "Sign in"
  }

  renderCatNav();
  renderProducts();
  renderCartCount();
  renderCartDrawer();
}
init();
})();
