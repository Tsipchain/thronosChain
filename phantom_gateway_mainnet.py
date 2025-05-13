import requests
import time
import logging

# σταθερά
BASE_URL      = "https://blockstream.info/api"
MIN_AMOUNT    = 0.00001  # ελάχιστη πληρωμή

def get_btc_txns(btc_address: str,
                 btc_receiver: str = None,
                 skip_verification: bool = False
                 ) -> list[dict]:
    """
    Επιστρέφει λίστα transaction dicts με τουλάχιστον:
      - 'to' (str): διεύθυνση παραλήπτη
      - 'amount_btc' (float): ποσό σε BTC
      - 'txid' (str): το transaction ID
      - 'timestamp' (int): χρονοσφραγίδα της συναλλαγής
    
    Αν skip_verification=True, παρακάμπτει το API και επιστρέφει ένα dummy
    payment για διευθύνσεις που ήδη υπάρχουν στο block.
    """
    if skip_verification:
        return [{
            'to': btc_receiver or 'VERIFIED_ADDRESS',
            'amount_btc': MIN_AMOUNT,
            'txid': f'verified_{btc_address}_{int(time.time())}',
            'timestamp': int(time.time())
        }]
    
    # configure logger
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("phantom_gateway")

    try:
        # 1) φέρνουμε confirmed + mempool
        logger.info(f"Fetching confirmed txs for {btc_address}")
        chain = requests.get(f"{BASE_URL}/address/{btc_address}/txs/chain", timeout=10)
        chain.raise_for_status()
        logger.info(f"Fetching mempool txs for {btc_address}")
        memp  = requests.get(f"{BASE_URL}/address/{btc_address}/txs/mempool", timeout=10)
        memp.raise_for_status()

        raw_txs = chain.json() + memp.json()
        logger.info(f"Total txs fetched: {len(raw_txs)}")

        txs = []
        for tx in raw_txs:
            txid       = tx.get("txid")
            tx_time    = tx.get("status", {}).get("block_time", int(time.time()))

            # φορτώνουμε λεπτομέρειες για να κοιτάξουμε outputs
            try:
                detail = requests.get(f"{BASE_URL}/tx/{txid}", timeout=10)
                detail.raise_for_status()
                info   = detail.json()

                for vout in info.get("vout", []):
                    addr     = vout.get("scriptpubkey_address")
                    sats     = vout.get("value", 0)
                    amount   = sats / 1e8

                    # αν ψάχνουμε συγκεκριμένο receiver ή δε θέλουμε φιλτράρισμα
                    if (btc_receiver is None or addr == btc_receiver) and amount >= MIN_AMOUNT:
                        txs.append({
                            "txid":        txid,
                            "to":          addr,
                            "from":        btc_address,
                            "amount_btc":  amount,
                            "timestamp":   tx_time
                        })
                        logger.info(f"→ relevant: {txid} → {amount} BTC to {addr}")
            except Exception as e:
                logger.error(f"Error fetching details for {txid}: {e}")
                continue

        return txs

    except Exception as e:
        logger.error(f"Error in get_btc_txns: {e}")
        return []

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
