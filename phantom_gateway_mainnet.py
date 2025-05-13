import requests
import time
import logging
from typing import List, Dict

# Βασικό URL του Blockstream API
BASE_URL   = "https://blockstream.info/api"
MIN_AMOUNT = 0.00001  # ελάχιστο ποσό σε BTC για να θεωρηθεί valid

def get_btc_txns(
    btc_address: str,
    btc_receiver: str = None,
    skip_verification: bool = False
) -> List[Dict]:
    """
    Επιστρέφει λίστα transaction dicts με τα πεδία:
      - 'txid'       : str
      - 'to'         : str
      - 'from'       : str
      - 'amount_btc' : float
      - 'timestamp'  : int
    Αν skip_verification=True, παρακάμπτει το πραγματικό query.
    """
    # Παράκαμψη (π.χ. για testing)
    if skip_verification:
        return [{
            'txid':       f'verified_{btc_address}_{int(time.time())}',
            'to':         btc_receiver or 'VERIFIED_ADDRESS',
            'from':       btc_address,
            'amount_btc': MIN_AMOUNT,
            'timestamp':  int(time.time())
        }]

    # Logger
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    logger = logging.getLogger("phantom_gateway")

    try:
        # Φόρτωσε confirmed txs
        logger.info(f"Fetching confirmed txs for {btc_address}")
        r_chain = requests.get(f"{BASE_URL}/address/{btc_address}/txs", timeout=10)
        r_chain.raise_for_status()

        # Φόρτωσε mempool txs
        logger.info(f"Fetching mempool txs for {btc_address}")
        r_memp  = requests.get(f"{BASE_URL}/address/{btc_address}/txs/mempool", timeout=10)
        r_memp.raise_for_status()

        raw_txs = r_chain.json() + r_memp.json()
        logger.info(f"Total fetched txs: {len(raw_txs)}")

        txs = []
        seen_txids = set()  # για να μην ξαναπροσθέτουμε το ίδιο tx

        for tx in raw_txs:
            txid = tx.get("txid")
            if not txid or txid in seen_txids:
                continue

            # timestamp: αν είναι confirmed, παίρνουμε το block_time, αλλιώς τώρα()
            tx_timestamp = tx.get("status", {}).get("block_time", int(time.time()))

            # Φόρτωσε λεπτομέρειες για outputs
            try:
                r_d = requests.get(f"{BASE_URL}/tx/{txid}", timeout=10)
                r_d.raise_for_status()
                info = r_d.json()

                # Κοιτάμε κάθε vout
                for vout in info.get("vout", []):
                    addr   = vout.get("scriptpubkey_address")
                    sats   = vout.get("value", 0)
                    amount = sats / 1e8

                    # Αν είναι προς τη σωστή διεύθυνση (ή δεν έχουμε φίλτρο)
                    # και ξεπερνάει το ελάχιστο ποσό
                    if (btc_receiver is None or addr == btc_receiver) and amount >= MIN_AMOUNT:
                        txs.append({
                            "txid":       txid,
                            "to":         addr,
                            "from":       btc_address,
                            "amount_btc": amount,
                            "timestamp":  tx_timestamp
                        })
                        logger.info(f"→ {txid}: {amount:.8f} BTC to {addr}")
                        seen_txids.add(txid)  # σημειώνουμε ότι το είδαμε
                        break  # δεν ψάχνουμε άλλα vouts για αυτό το tx
            except Exception as e:
                logger.error(f"Error fetching details for {txid}: {e}")
                # προχωράμε στην επόμενη tx
                continue

        return txs

    except Exception as e:
        logger.error(f"Error in get_btc_txns: {e}")
        return []
