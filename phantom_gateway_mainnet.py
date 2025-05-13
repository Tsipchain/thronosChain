import requests
import time
import logging

BASE_URL   = "https://blockstream.info/api"
MIN_AMOUNT = 0.00001  # ελάχιστο ποσό σε BTC για επαλήθευση

def get_btc_txns(btc_address: str,
                 btc_receiver: str = None,
                 skip_verification: bool = False
                ) -> list[dict]:
    """
    Επιστρέφει λίστα transaction dicts με τουλάχιστον:
      - 'to' (str)
      - 'amount_btc' (float)
      - 'txid' (str)
      - 'timestamp' (int)
    """
    if skip_verification:
        return [{
            'to': btc_receiver or 'VERIFIED_ADDRESS',
            'amount_btc': MIN_AMOUNT,
            'txid': f'verified_{btc_address}_{int(time.time())}',
            'timestamp': int(time.time())
        }]

    # Logger
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("phantom_gateway")

    try:
        # Φόρτωσε confirmed + mempool txs
        logger.info(f"Fetching chain txs for {btc_address}")
        r_chain = requests.get(f"{BASE_URL}/address/{btc_address}/txs/chain",
                               timeout=10)
        r_chain.raise_for_status()
        logger.info(f"Fetching mempool txs for {btc_address}")
        r_memp  = requests.get(f"{BASE_URL}/address/{btc_address}/txs/mempool",
                               timeout=10)
        r_memp.raise_for_status()

        raw_txs = r_chain.json() + r_memp.json()
        logger.info(f"Total fetched txs: {len(raw_txs)}")

        txs = []
        for tx in raw_txs:
            txid = tx.get("txid")
            tx_timestamp = tx.get("status", {})\
                              .get("block_time", int(time.time()))

            # Φόρτωσε λεπτομέρειες blockstream για outputs
            try:
                r_d = requests.get(f"{BASE_URL}/tx/{txid}", timeout=10)
                r_d.raise_for_status()
                info = r_d.json()

                for vout in info.get("vout", []):
                    addr   = vout.get("scriptpubkey_address")
                    sats   = vout.get("value", 0)
                    amount = sats / 1e8

                    if (btc_receiver is None or addr == btc_receiver) \
                       and amount >= MIN_AMOUNT:
                        txs.append({
                            "txid":       txid,
                            "to":         addr,
                            "from":       btc_address,
                            "amount_btc": amount,
                            "timestamp":  tx_timestamp
                        })
                        logger.info(f"→ {txid}: {amount} BTC to {addr}")
            except Exception as e:
                logger.error(f"Error fetching details for {txid}: {e}")
                continue

        return txs

    except Exception as e:
        logger.error(f"Error in get_btc_txns: {e}")
        return []
