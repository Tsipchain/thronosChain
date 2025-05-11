import os
import json
import time
import hashlib
from flask import Flask, request, jsonify, render_template, send_from_directory
from phantom_gateway_mainnet import get_btc_txns  # Your BTC API

# Για τη δημιουργία PDF contracts
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
    base_reward = 1.0
    return round(base_reward / (2 ** halvings), 6)

def create_pdf_contract(btc_address, pledge_text, thr_address, filename):
    """Δημιουργία PDF contract με ReportLab με προηγμένες δυνατότητες"""
    pdf_path = os.path.join(CONTRACTS_DIR, filename)
    
    # Δημιουργία PDF με ReportLab
    c = canvas.Canvas(pdf_path, pagesize=letter)
    width, height = letter
    
    # Προσθήκη τίτλου και πλαισίου
    c.setFont("Helvetica-Bold", 18)
    c.drawString(1*inch, height-1*inch, "THRONOS BLOCKCHAIN CONTRACT")
    
    c.setFont("Helvetica-Bold", 12)
    c.drawString(1*inch, height-1.5*inch, f"Contract ID: {hashlib.sha256(thr_address.encode()).hexdigest()[:12]}")
    c.drawString(1*inch, height-1.8*inch, f"Date: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    
    # Διαχωριστική γραμμή
    c.setStrokeColorRGB(0.8, 0.8, 0.8)
    c.line(1*inch, height-2*inch, width-1*inch, height-2*inch)
    
    # Πληροφορίες συμβολαίου
    c.setFont("Helvetica-Bold", 12)
    c.drawString(1*inch, height-2.5*inch, "BTC Address:")
    c.setFont("Helvetica", 12)
    c.drawString(1*inch, height-2.8*inch, btc_address)
    
    c.setFont("Helvetica-Bold", 12)
    c.drawString(1*inch, height-3.3*inch, "Pledge Text:")
    c.setFont("Helvetica", 12)
    
    # Διαχείριση μεγάλων κειμένων pledge με αναδίπλωση
    text_object = c.beginText(1*inch, height-3.6*inch)
    text_object.setFont("Helvetica", 12)
    
    # Διαχωρισμός κειμένου σε γραμμές μέγιστου μήκους 80 χαρακτήρων
    lines = []
    words = pledge_text.split()
    current_line = ""
    
    for word in words:
        if len(current_line + " " + word) <= 80:
            current_line += (" " + word if current_line else word)
        else:
            lines.append(current_line)
            current_line = word
    
    if current_line:
        lines.append(current_line)
    
    for line in lines:
        text_object.textLine(line)
    
    c.drawText(text_object)
    
    # Διαχωριστική γραμμή
    c.setStrokeColorRGB(0.8, 0.8, 0.8)
    y_pos = height-3.6*inch - (len(lines) * 14) - 0.5*inch
    c.line(1*inch, y_pos, width-1*inch, y_pos)
    
    # THR Address
    c.setFont("Helvetica-Bold", 12)
    c.drawString(1*inch, y_pos - 0.4*inch, "Generated THR Address:")
    c.setFont("Helvetica", 12)
    c.drawString(1*inch, y_pos - 0.7*inch, thr_address)
    
    # Προσθήκη υπογραφής
    c.setFont("Helvetica-Oblique", 10)
    c.drawString(1*inch, 1*inch, "This contract is digitally signed and stored on the Thronos blockchain.")
    c.drawString(1*inch, 0.8*inch, f"Verification Hash: {hashlib.sha256((btc_address + thr_address).encode()).hexdigest()}")
    
    # Ολοκλήρωση του PDF
    c.save()
    
    return pdf_path

# ─── TEMPLATE ROUTES ──────────────────────────────
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/docs")
def docs():
    return render_template("tokenomics.html")

@app.route("/pledge")
def pledge_form():
    return render_template("pledge_form.html")

@app.route("/send")
def send_thr_form():
    return render_template("send_thr_form.html")

@app.route("/viewer")
def block_viewer():
    return render_template("thronos_block_viewer.html")

@app.route("/wallet")
def wallet_viewer():
    return render_template("wallet_viewer.html")

# ─── PLEDGE ENDPOINT ───────────────────────────────
@app.route("/pledge_submit", methods=["POST"])
def pledge_submit():
    data        = request.get_json() or {}
    btc_address = data.get("btc_address", "").strip()
    pledge_text = data.get("pledge_text", "").strip()

    if not btc_address:
        return jsonify(error="Missing BTC address"), 400

    pledges = load_json(PLEDGE_CHAIN, [])

    existing = next((p for p in pledges if p["btc_address"] == btc_address), None)
    if existing:
        return jsonify({
            "status":       "already_verified",
            "thr_address":  existing["thr_address"],
            "pledge_hash":  existing["pledge_hash"],
            "pdf_filename": f"pledge_{existing['thr_address']}.pdf"
        }), 200

    # Έλεγχος αν η διεύθυνση υπάρχει ήδη στο blockchain
    chain = load_json(CHAIN_FILE, [])
    address_in_chain = any(block.get('thr_address') == btc_address for block in chain if isinstance(block, dict))
    
    # Έλεγχος πληρωμής
    # Αν η διεύθυνση υπάρχει ήδη στο blockchain, παρακάμπτουμε την επαλήθευση
    txns = get_btc_txns(btc_address, BTC_RECEIVER, skip_verification=address_in_chain)
    paid = any(
        tx.get("to") == BTC_RECEIVER and float(tx.get("amount_btc", 0)) >= 0.00001
        for tx in txns
    )
    if not paid:
        return jsonify(status="pending",
                       message="Waiting for BTC payment to the pledge address."), 200

    # νέα δέσμευση
    thr_address = f"THR{int(time.time()*1000)}"
    pledge_hash = hashlib.sha256((btc_address + pledge_text).encode()).hexdigest()
    timestamp   = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())

    new_pledge = {
        "btc_address": btc_address,
        "pledge_text": pledge_text,
        "timestamp":   timestamp,
        "pledge_hash": pledge_hash,
        "thr_address": thr_address
    }
    pledges.append(new_pledge)
    save_json(PLEDGE_CHAIN, pledges)

    pdf_name = f"pledge_{thr_address}.pdf"
    create_pdf_contract(btc_address, pledge_text, thr_address, pdf_name)

    return jsonify({
        "status":       "verified",
        "thr_address":  thr_address,
        "pledge_hash":  pledge_hash,
        "pdf_filename": pdf_name
    }), 200

# serve τα generated PDF
@app.route("/contracts/<path:filename>")
def serve_contract(filename):
    return send_from_directory(CONTRACTS_DIR, filename)

# ─── BLOCKCHAIN & TOKEN ENDPOINTS ────────────────
@app.route("/chain", methods=["GET"])
def get_chain():
    return jsonify(load_json(CHAIN_FILE, [])), 200

@app.route("/submit_block", methods=["POST"])
def submit_block():
    data = request.get_json()
    if not isinstance(data, dict):
        return jsonify(error="Invalid block data"), 400

    chain  = load_json(CHAIN_FILE, [])
    height = len(chain)

    reward   = calculate_reward(height)
    pool_fee = 0.005

    data.setdefault("timestamp",    time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()))
    data.setdefault("block_hash",   f"THR-{height}")
    data["reward"]          = reward
    data["pool_fee"]        = pool_fee
    data["reward_to_miner"] = round(reward - pool_fee, 6)

    chain.append(data)
    save_json(CHAIN_FILE, chain)

    return jsonify({
        "status":         "ok",
        "block_hash":     data["block_hash"],
        "thr_address":    data.get("thr_address"),
        "reward":         reward,
        "reward_to_miner": data["reward_to_miner"]
    }), 200

@app.route("/wallet_data/<thr_address>", methods=["GET"])
def wallet_data(thr_address):
    ledger = load_json(LEDGER_FILE, {})
    chain  = load_json(CHAIN_FILE, [])
    balance = ledger.get(thr_address, 0.0)

@app.route("/wallet/<thr_address>", methods=["GET"])
def wallet_redirect(thr_address):
    return redirect(url_for('wallet_data', thr_address=thr_address))

    history = [
        tx for tx in chain
        if isinstance(tx, dict) and (
           tx.get("from")==thr_address or tx.get("to")==thr_address
        )
    ]
    return jsonify(balance=round(balance,6), transactions=history), 200

@app.route("/send_token", methods=["POST"])
def send_token():
    data      = request.get_json() or {}
    sender    = data.get("from","").strip()
    recipient = data.get("to","").strip()
    try:
        amount = round(float(data.get("amount",0)),6)
    except:
        return jsonify(error="Invalid amount"), 400

    if not sender or not recipient or amount<=0:
        return jsonify(error="Invalid input"), 400

    ledger = load_json(LEDGER_FILE,{})
    fee    = 0.0015
    total  = round(amount+fee,6)
    if ledger.get(sender,0.0)<total:
        return jsonify(error="Insufficient balance"),403

    ledger[sender]    = round(ledger.get(sender,0.0)-total,6)
    ledger[recipient] = round(ledger.get(recipient,0.0)+amount,6)
    save_json(LEDGER_FILE,ledger)

    chain = load_json(CHAIN_FILE,[])
    tx = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "from":      sender,
        "to":        recipient,
        "amount":    amount,
        "fee":       fee
    }
    chain.append(tx)
    save_json(CHAIN_FILE,chain)
    from flask import redirect, url_for, send_from_directory

# ——————————————————————————————————————————————————————
# Serve τα PDF που παράγονται (τα έβαλες στο static/contracts)
@app.route("/contracts/<path:filename>")
def serve_contract(filename):
    return send_from_directory(os.path.join(app.root_path, "static", "contracts"), filename)

# ——————————————————————————————————————————————————————
# Endpoint που επιστρέφει JSON balance + history
@app.route("/wallet_data/<thr_addr>", methods=["GET"])
def wallet_data(thr_addr):
    ledger = load_json(LEDGER_FILE, {})
    chain  = load_json(CHAIN_FILE, [])
    balance = round(ledger.get(thr_addr, 0.0), 6)
    history = [
        tx for tx in chain
        if tx.get("from") == thr_addr or tx.get("to") == thr_addr
    ]
    return jsonify(balance=balance, transactions=history), 200

# ——————————————————————————————————————————————————————
# Redirect από το /wallet/XXX στο /wallet_data/XXX
@app.route("/wallet/<thr_addr>", methods=["GET"])
def wallet_redirect(thr_addr):
    return redirect(url_for("wallet_data", thr_addr=thr_addr))


    return jsonify(status="OK", tx=tx),200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
