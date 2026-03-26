"""
Diagnostic: verify your Polymarket wallet credentials before running the bot.
Usage: python3 check_wallet.py
"""
import os
import sys

from dotenv import load_dotenv
load_dotenv()

from config import PRIVATE_KEY, FUNDER_ADDRESS, POLY_SIGNATURE_TYPE

def main():
    if not PRIVATE_KEY:
        print("\n[ERROR] PRIVATE_KEY is empty in .env")
        print("  See instructions below to get your private key.\n")
        _print_help()
        return

    from eth_account import Account
    import requests

    signer = Account.from_key(PRIVATE_KEY).address
    funder = FUNDER_ADDRESS or signer
    rpc = "https://polygon-rpc.com"
    usdc_e = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

    print(f"\n{'='*60}")
    print(f"  Polymarket Wallet Diagnostic")
    print(f"{'='*60}")
    print(f"  Signer (from PRIVATE_KEY):  {signer}")
    print(f"  Funder (FUNDER_ADDRESS):    {funder}")
    print(f"  Signature type:             {POLY_SIGNATURE_TYPE}")
    print()

    def balance_of(addr):
        padded = addr[2:].lower().zfill(64)
        r = requests.post(rpc, json={
            "jsonrpc": "2.0", "id": 1, "method": "eth_call",
            "params": [{"to": usdc_e, "data": "0x70a08231" + padded}, "latest"],
        }, timeout=10)
        return int(r.json().get("result", "0x0"), 16) / 1e6

    def nonce_of(addr):
        r = requests.post(rpc, json={
            "jsonrpc": "2.0", "id": 1, "method": "eth_getTransactionCount",
            "params": [addr, "latest"],
        }, timeout=10)
        return int(r.json().get("result", "0x0"), 16)

    def is_contract(addr):
        r = requests.post(rpc, json={
            "jsonrpc": "2.0", "id": 1, "method": "eth_getCode",
            "params": [addr, "latest"],
        }, timeout=10)
        code = r.json().get("result", "0x")
        return code not in ("0x", "0x0")

    signer_bal = balance_of(signer)
    signer_nonce = nonce_of(signer)
    funder_bal = balance_of(funder)
    funder_nonce = nonce_of(funder)
    funder_is_contract = is_contract(funder) if funder != signer else False

    print(f"  Signer on-chain:  ${signer_bal:.2f} USDC.e, {signer_nonce} txns")
    print(f"  Funder on-chain:  ${funder_bal:.2f} USDC.e, {funder_nonce} txns, contract={funder_is_contract}")

    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import BalanceAllowanceParams, AssetType

    print(f"\n  CLOB balance check (all sig types):")
    for st in [0, 1, 2]:
        try:
            c = ClobClient(
                "https://clob.polymarket.com",
                key=PRIVATE_KEY, chain_id=137,
                signature_type=st,
                funder=funder if st > 0 else None,
            )
            creds = c.create_or_derive_api_creds()
            c.set_api_creds(creds)
            params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=st)
            info = c.get_balance_allowance(params)
            bal = int(info.get("balance", "0")) / 1e6
            has_allow = any(int(v) > 0 for v in info.get("allowances", {}).values())
            marker = " <-- HAS FUNDS" if bal > 0 else ""
            print(f"    sig_type={st}: ${bal:.2f}, allowances={'YES' if has_allow else 'no'}{marker}")
        except Exception as e:
            print(f"    sig_type={st}: ERROR - {e}")

    print()

    ok = signer_bal > 0 or funder_bal > 0
    if ok:
        print("  [OK] Funds detected! Your credentials look correct.")
    else:
        if signer_nonce == 0 and funder_nonce == 0:
            print("  [FAIL] Both signer and funder have NEVER been used on Polygon.")
            print("         Your PRIVATE_KEY does NOT match your Polymarket account.")
        else:
            print("  [FAIL] Zero USDC.e balance. You may need to deposit funds.")

        print()
        _print_help()

def _print_help():
    print("  HOW TO GET THE CORRECT PRIVATE KEY:")
    print("  ====================================")
    print()
    print("  Option A — You signed up with EMAIL or GOOGLE:")
    print("    1. Go to: https://reveal.magic.link/polymarket")
    print("       (you MUST be logged into Polymarket.com first)")
    print("    2. Sign in with the SAME email/Google you use on Polymarket")
    print("    3. Click 'Reveal Private Key' → copy the hex string")
    print("    4. Paste into .env as: PRIVATE_KEY=0x...")
    print("    5. Set POLY_SIGNATURE_TYPE=1")
    print()
    print("  Option B — You signed up with METAMASK / browser wallet:")
    print("    1. Open MetaMask → click account menu → Account Details")
    print("    2. Click 'Export Private Key' → enter your MetaMask password")
    print("    3. Copy the hex key")
    print("    4. Paste into .env as: PRIVATE_KEY=0x...")
    print("    5. Set POLY_SIGNATURE_TYPE=2")
    print()
    print("  HOW TO GET THE CORRECT FUNDER_ADDRESS:")
    print("  =======================================")
    print("    1. Go to Polymarket.com")
    print("    2. Click your profile icon (top-right corner)")
    print("    3. Your wallet address is shown in the dropdown")
    print("    4. Paste into .env as: FUNDER_ADDRESS=0x...")
    print()
    print("  Or try: https://polymarket.com/settings?tab=export-private-key")
    print()

if __name__ == "__main__":
    main()
