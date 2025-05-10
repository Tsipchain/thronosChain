
import requests
import time
import logging

def get_btc_txns(btc_address: str, btc_receiver: str = None, skip_verification: bool = False) -> list[dict]:
    """
    Επιστρέφει λίστα transaction dicts με τουλάχιστον:
      - 'to' (str): διεύθυνση παραλήπτη
      - 'amount_btc' (float): ποσό σε BTC
      - 'txid' (str): το transaction ID
      - 'timestamp' (int): χρονοσφραγίδα της συναλλαγής
    
    Χρησιμοποιεί το Blockstream API για να λάβει τις συναλλαγές.
    Παράμετρος skip_verification: Αν είναι True, δεν γίνεται έλεγχος και επιστρέφει απευθείας τα στοιχεία
    για διευθύνσεις που υπάρχουν ήδη στο block.
    """
    # Αν είναι διεύθυνση που υπάρχει ήδη στο block και ζητείται παράκαμψη ελέγχου
    if skip_verification:
        # Επιστροφή στοιχείων χωρίς έλεγχο για διευθύνσεις που είναι ήδη στο block
        return [{
            'to': btc_receiver or 'VERIFIED_ADDRESS',
            'amount_btc': 0.00001,  # Ελάχιστο ποσό για επαλήθευση
            'txid': f'verified_{btc_address}_{int(time.time())}',
            'timestamp': int(time.time())
        }]
        
    try:
        # Configure logging for debugging
        logging.basicConfig(level=logging.INFO)
        logger = logging.getLogger("phantom_gateway")
        
        # Use Blockstream API to get transaction history
        logger.info(f"Fetching transactions for address: {btc_address}")
        resp = requests.get(
            f"https://blockstream.info/api/address/{btc_address}/txs",
            timeout=10  # Add timeout to prevent hanging requests
        )
        resp.raise_for_status()
        raw_txs = resp.json()
        logger.info(f"Found {len(raw_txs)} transactions")
        
        # Process transactions and outputs
        txs = []
        for tx in raw_txs:
            txid = tx.get("txid")
            tx_timestamp = tx.get("status", {}).get("block_time", int(time.time()))
            
            # Get detailed transaction info to check outputs properly
            try:
                tx_detail_resp = requests.get(
                    f"https://blockstream.info/api/tx/{txid}",
                    timeout=10
                )
                tx_detail_resp.raise_for_status()
                tx_detail = tx_detail_resp.json()
                
                # Process outputs (vout) to find relevant transactions
                for vout in tx_detail.get("vout", []):
                    addr = vout.get("scriptpubkey_address")
                    amt_sats = vout.get("value", 0)
                    amt_btc = amt_sats / 1e8
                    
                    # Only include transactions if they're relevant to our query
                    if btc_receiver is None or addr == btc_receiver:
                        txs.append({
                            "txid": txid,
                            "to": addr,
                            "from": btc_address,  # Approximate, might not be accurate for all outputs
                            "amount_btc": amt_btc,
                            "timestamp": tx_timestamp
                        })
                        logger.info(f"Found relevant transaction: {txid} - {amt_btc} BTC to {addr}")
            except Exception as tx_err:
                logger.error(f"Error getting transaction details for {txid}: {tx_err}")
                continue
                
        return txs
    except Exception as e:
        logging.error(f"Error in get_btc_txns: {str(e)}")
        # If API call fails, return empty list
        return []
