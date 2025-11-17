import asyncio
import logging
import os
import time

import cdp
from cdp import CdpClient  # pip install cdp-sdk
from dotenv import load_dotenv
from common.config_logging import to_stdout

'''
Refer to https://docs.cdp.coinbase.com/faucets/introduction/welcome

'''
async def get_or_create_account_and_request_fund(network="base-sepolia", number_of_token=1, account_name="TEST-ACCOUNT",
                                                 token="eth"):
    # read key and secret from environment variable file
    base_dir = os.path.dirname(os.path.abspath(__file__))  # directory where this script is located
    dotenv_path = os.path.join(base_dir, 'vault', 'coinbase_keys')  # adjust '..' if needed
    load_dotenv(dotenv_path=dotenv_path)

    cdp = CdpClient(debugging=True)
    try:

        account = await cdp.evm.get_or_create_account(name=account_name)
        logging.info(f"EVM Address: {account.address}")

        logging.info(f"Creating {number_of_token} {token}")
        for i in range(number_of_token):
            logging.info(f"Creating {token} : {i + 1} time(s)")
            faucet_hash = await cdp.evm.request_faucet(
                address=account.address,
                network=network,
                token=token
            )
            logging.info(f"Requested funds for {token} faucet: https://sepolia.basescan.org/tx/{faucet_hash}")
            time.sleep(1)
            logging.info("Closing Client..")
            await cdp.close()
    except Exception as e:
        logging.error(f"Exception Occurred {e}")
        logging.info("Closing Client..")
        await cdp.close()

async def transfer():
    from web3 import Web3
    w3 = Web3(Web3.HTTPProvider("https://sepolia.base.org"))
    # read key and secret from environment variable file
    base_dir = os.path.dirname(os.path.abspath(__file__))  # directory where this script is located
    dotenv_path = os.path.join(base_dir, 'vault', 'coinbase_keys')  # adjust '..' if needed
    load_dotenv(dotenv_path=dotenv_path)

    cdp = CdpClient(debugging=True)
    sender = await cdp.evm.get_or_create_account(name="TEST-ACCOUNT")
    receiver = await cdp.evm.get_or_create_account(name="TEST-ACCOUNT-RECEIVER")

    tx_hash = await sender.transfer(
        to="0x8e24E42c4Bd3f9DaB285F6DcE4377Ba4fF54c91F",
        amount=w3.to_wei("0.0001", "ether"),
        token="eth",
        network="base-sepolia"
    )

    print(f"Transaction : https://sepolia.basescan.org/tx/{tx_hash}")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    print(f"Receipt: {receipt}")
    await cdp.close()

if __name__ == "__main__":
    to_stdout()
    # # 10 USDC every 24 hrs
    # asyncio.run(get_or_create_account_and_request_fund(token='usdc', number_of_token=10))
    # # 1000 ETH every 24 hrs
    # asyncio.run(get_or_create_account_and_request_fund(token='eth', number_of_token=1000))
    # asyncio.run(transfer())
