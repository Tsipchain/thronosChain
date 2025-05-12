import os
import json
import time
import hashlib
from flask import (
    Flask, request, jsonify,
    render_template, send_from_directory,
    redirect, url_for
)
from phantom_gateway_mainnet import get_btc_txns
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch

app = Flask(__name__)

# ─── CONFIG ────────────────────────────────────────
LEDGER_FILE   = "ledger.json"
CHAIN_FILE    = "phantom_tx_chain.json"
PLEDGE_CHAIN  = "pledge_chain.json"
BTC_RECEIVER  = "1FQov4P8yzUU1Af4C5QNyAfQauc4maytKo"
CONTRACTS_DIR = os.path.join(app.root_path, "templates", "contracts")
os.makedirs(CONTRACTS_DIR, exist_ok=True)

# ─── HELPERS ───────────────────────────────────────
def load_json(path, default):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def calculate_reward(block_height: int) -> float:
    halvings = block_height // 210000
    return round(1.0 / (2 ** halvings), 6)

def create_pdf_contract(btc_addr, pledge_text, thr_addr, filename):
    pdf_path = os.path.join(CONTRACTS_DIR, filename)
    c = canvas.Canvas(pdf_path, pagesize=letter)
    w, h = letter

    c.setFont("Helvetica-Bold", 18)
    c.drawString(1*inch, h-1*inch, "THRONOS BLOCKCHAIN CONTRACT")
    c.setFont("Helvetica", 12)
    c.drawString(1*inch, h-1.5*inch, f"BTC Address: {btc_addr}")
    c.drawString(1*inch, h-1.8*inch, f"Pledge Text:")
    text_obj = c.beginText(1*inch, h-2.1*inch)
    text_obj.setFont("Helvetica", 12)
    # wrap at 80 chars
    line, lines = "", []
    for word in pledge_text.split():
        if len(line + " " + word) <= 80:
            line += (" " + word if line else word)
        else:
            lines.append(line)
            line = word
    if line: lines.append(line)
    for l in lines:
        text_obj.textLine(l)
    c.drawText(text_obj)

    c.drawString(1*inch, h-2.1*inch - (len(lines)*14) - 20, f"Generated THR Address: {thr_addr}")
    c.save()
    return pdf_path

# ─── TEMPLATE ROUTES ──────────────────────────────
@app.route("/")
def home():    return render_template("index.html")
@app.route("/docs")
def docs():    return render_template("tokenomics.html")
@app.route("/pledge")
def pledge():  return render_template("pledge_form.html")
@app.route("/send")
def send_thr():return render_template("send_thr_form.html")
@app.route("/viewer")
def viewer():  return render_template("thronos_block_viewer.html")
@app.route("/wallet")
def wallet():  return render_template("wallet_viewer.html")

# ─── PLEDGE SUBMIT ────────────────────────────────
@app.route("/pledge_submit", methods=["POST"])
def pledge_submit():
    data        = request.get_json() or {}
    btc_address = data.get("btc_address","").strip()
    pledge_text = data.get("pledge_text","").strip()
    if not btc_address:
        return jsonify(error="Missing BTC address"), 400

    pledges = load_json(PLEDGE_CHAIN, [])
    existing = next((p for p in pledges if p["btc_address"]==btc_address), None)
    if existing:
        return jsonify({
            "status":      "already_verified",
            "thr_address": existing["thr_address"],
            "pledge_hash": existing["pledge_hash"],
            "pdf_filename": f"pledge_{existing['thr_address']}.pdf"
        }), 200

    # έλεγχος συναλλαγής
    txns = get_btc_txns(btc_address, BTC_RECEIVER)
    paid = any(
        tx.get("to")==BTC_RECEIVER and float(tx.get("amount_btc",0))>=0.00001
        for tx in txns
    )
    if not paid:
        return jsonify(status="pending", message="Waiting for BTC payment"), 200

    # δημιουργία νέας δέσμευσης
    thr_addr   = f"THR{int(time.time()*1000)}"
    phash      = hashlib.sha256((btc_address+pledge_text).encode()).hexdigest()
    pledges.append({
        "btc_address": btc_address,
        "pledge_text": pledge_text,
        "timestamp":   time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "pledge_hash": phash,
        "thr_address": thr_addr
    })
    save_json(PLEDGE_CHAIN, pledges)

    pdf_name = f"pledge_{thr_addr}.pdf"
    create_pdf_contract(btc_address, pledge_text, thr_addr, pdf_name)
    return jsonify(
        status="verified",
        thr_address=thr_addr,
        pledge_hash=phash,
        pdf_filename=pdf_name
    ), 200

# ─── SERVE CONTRACT PDFs ──────────────────────────
@app.route("/contracts/<path:filename>")
def serve_contract(filename):
    return send_from_directory(CONTRACTS_DIR, filename)

# ─── BLOCKCHAIN & TOKENS ─────────────────────────
@app.route("/chain", methods=["GET"])
def get_chain():
    return jsonify(load_json(CHAIN_FILE,[])), 200

@app.route("/submit_block", methods=["POST"])
def submit_block():
    data  = request.get_json() or {}
    chain = load_json(CHAIN_FILE, [])
    h     = len(chain)
    r     = calculate_reward(h)
    fee   = 0.005

    data.setdefault("timestamp",    time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()))
    data.setdefault("block_hash",   f"THR-{h}")
    data["reward"]          = r
    data["pool_fee"]        = fee
    data["reward_to_miner"] = round(r-fee,6)

    chain.append(data)
    save_json(CHAIN_FILE, chain)
    return jsonify({"status":"ok", **data}), 200

@app.route("/wallet_data/<thr_addr>", methods=["GET"])
def wallet_data(thr_addr):
    ledger = load_json(LEDGER_FILE, {})
    chain  = load_json(CHAIN_FILE, [])
    bal    = round(ledger.get(thr_addr,0.0),6)
    history = [
        tx for tx in chain
        if isinstance(tx, dict) and (tx.get("from")==thr_addr or tx.get("to")==thr_addr)
    ]
    return jsonify(balance=bal, transactions=history), 200

@app.route("/wallet/<thr_addr>", methods=["GET"])
def wallet_redirect(thr_addr):
    return redirect(url_for("wallet_data", thr_addr=thr_addr))

@app.route("/send_token", methods=["POST"])
def send_token():
    data      = request.get_json() or {}
    frm, to_  = data.get("from","").strip(), data.get("to","").strip()
    try:
        amt = round(float(data.get("amount",0)),6)
    except:
        return jsonify(error="Invalid amount"), 400
    if not frm or not to_ or amt<=0:
        return jsonify(error="Invalid input"), 400

    ledger = load_json(LEDGER_FILE,{})
    fee    = 0.0015
    total  = round(amt+fee,6)
    if ledger.get(frm,0.0)<total:
        return jsonify(error="Insufficient balance"), 403

    ledger[frm]   = round(ledger.get(frm,0.0)-total,6)
    ledger[to_]   = round(ledger.get(to_,0.0)+amt,6)
    save_json(LEDGER_FILE, ledger)

    tx = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "from":      frm,
        "to":        to_,
        "amount":    amt,
        "fee":       fee
    }
    chain = load_json(CHAIN_FILE,[])
    chain.append(tx)
    save_json(CHAIN_FILE, chain)
    return jsonify(status="OK", tx=tx), 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=True)

