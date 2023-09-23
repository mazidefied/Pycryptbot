import threading
import requests
import time
import json
from eth_account import Account
from telegram import Update
from telegram.ext import CallbackContext, CommandHandler, Updater
from web3 import Web3
from web3.middleware import geth_poa_middleware
import logging
from requests.exceptions import Timeout, ConnectionError
from abis import token_pair_abi
import datetime

alchemy_url = "https://eth-mainnet.g.alchemy.com/v2/7jSvlZt1FLEfOxQBadrQb93cMGmLyqjN"
w3 = Web3(Web3.HTTPProvider(alchemy_url))

# Print if web3 is successfully connected
print(w3.is_connected())

# Get the latest block number
latest_block = w3.eth.get_block("latest")
print(latest_block)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)


with open('ERC20_ABI.json') as f:
    ERC20_ABI = json.load(f)

with open('uniswap_factory_abi.json') as f:
    uniswap_factory_abi = json.load(f)

with open('pancakeswap_factory_abi.json') as f:
    pancakeswap_factory_abi = json.load(f)

with open('uniswap_router_abi.json') as f:
    uniswap_router_abi = json.load(f)

with open('pancakeswap_router_abi.json') as f:
    pancakeswap_router_abi = json.load(f)

with open('token_pair_abi.json', 'w') as f:
    json.dump(token_pair_abi, f)


ETHEREUM_RPC_URL = "https://eth-mainnet.g.alchemy.com/v2/7jSvlZt1FLEfOxQBadrQb93cMGmLyqjN"
web3_eth = Web3(Web3.HTTPProvider(ETHEREUM_RPC_URL))
web3_eth.middleware_onion.inject(geth_poa_middleware, layer=0)

bsc_rpc_url = "https://bsc-dataseed1.binance.org/"
web3_bsc = Web3(Web3.HTTPProvider(bsc_rpc_url))
web3_bsc.middleware_onion.inject(geth_poa_middleware, layer=0)

UNISWAP_FACTORY_ADDRESS = "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f"

PANCAKESWAP_FACTORY_ADDRESS = "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"

pancakeswap_factory_abi = json.loads(pancakeswap_factory_abi)
print(pancakeswap_factory_abi)

uniswap_factory_address_checksum = Web3.to_checksum_address(UNISWAP_FACTORY_ADDRESS)

pancakeswap_factory_address_checksum = Web3.to_checksum_address(PANCAKESWAP_FACTORY_ADDRESS)

uniswap_factory = web3_eth.eth.contract(
    address=uniswap_factory_address_checksum, abi=uniswap_factory_abi
)
pancakeswap_factory = web3_bsc.eth.contract(
    address=pancakeswap_factory_address_checksum, abi=pancakeswap_factory_abi
)


private_key = "eea50064fa64ac2e7e834459640139f7447a476390b1e851f135c1fc0aafd677"
user_address = "0x2630E27F5f7B12501eC8b80DAB7Fe24eb239eF8C"
account = Account.from_key(private_key)

uniswap_router_address = 0x7A250D5630B4CF539739DF2C5DACB4C659F2488D

pancakeswap_router_address = 0x10ED43C718714EB63D5AA57B78B54704E256024E

weth_address = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
web3_provider = "https://eth-mainnet.g.alchemy.com/v2/7jSvlZt1FLEfOxQBadrQb93cMGmLyqjN"
wbnb_address = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"

MAX_GAS_PRICE_ETH = 10000000000000
MAX_GAS_PRICE_BSC = 10000000000000


local_erc20_abi = {}
newly_listed_not_tradable_pairs = []
verifying_tokens = []
waiting_for_successful_swap = []
still_not_tradable_check_info = {}
local_router_abi = {}
reported_tokens = {}

purchase_amount_uniswap = 0.0
purchase_amount_pancakeswap = 0.0
def get_router_abi(router_address, is_bsc=False):
    # Überprüfen Sie, ob die ABI bereits lokal gespeichert ist
    if router_address in local_router_abi:
        return local_router_abi[router_address]

    # Andernfalls versuchen Sie, die ABI von der API zu erhalten
    if is_bsc:
        base_url = "https://api.bscscan.com"
        api_key = "4I9ZTHBDPQCSTI1JD9KNZSABZ9FY5CJKHS"
        router_abi = pancakeswap_router_abi
    else:
        base_url = "https://api.etherscan.io"
        api_key = "U7NDP99ZNMCKW7AH5PWC7CFMKBI81BBC35"
        router_abi = uniswap_router_abi

    url = f"{base_url}/api?module=contract&action=getabi&address={router_address}&apikey={api_key}"

    retry_count = 0
    response = None
    while retry_count < 3:
        try:
            response = requests.get(url)
            response_json = response.json()

            if response_json["status"] == "1" and response_json["result"]:
                router_abi = json.loads(response_json["result"])

                # Log successful fetch
                print(f"Successfully fetched ABI for router {router_address}.")

                # Speichern Sie die ABI lokal für zukünftige Verwendung
                local_router_abi[router_address] = router_abi
                return router_abi
            else:
                logging.error(f"Failed to fetch ABI for router address {router_address}. Response: {response_json}")
                retry_count += 1
                time.sleep(3)
        except Exception as e:
            logging.error(
                f"Exception while fetching ABI: {e}. Response: {response.text if response else 'No response'}")

    logging.warning(f"Failed to fetch ABI for router address {router_address} after multiple attempts.")
    return router_abi


def display_verifying_tokens():
    print("Verifying Tokens:")
    for token_address in verifying_tokens:
        print(token_address)


def is_contract_verified(token_address, is_bsc=False, retries=3):
    if is_bsc:
        base_url = "https://api.bscscan.com"
        api_key = "4I9ZTHBDPQCSTI1JD9KNZSABZ9FY5CJKHS"
    else:
        base_url = "https://api.etherscan.io"
        api_key = "U7NDP99ZNMCKW7AH5PWC7CFMKBI81BBC35"

    url = f"{base_url}/api?module=contract&action=getsourcecode&address={token_address}&apikey={api_key}"

    for _ in range(retries):
        try:
            response = requests.get(url, timeout=10)  # Set a timeout to prevent hanging indefinitely
            response_json = response.json()

            if response_json["status"] == "1" and response_json["result"]:
                contract_info = response_json["result"][0]
                if bool(contract_info["ContractName"] and contract_info["SourceCode"]):  # Prüft sowohl ContractName als auch SourceCode
                    print(f"Contract for token {token_address} is verified.")
                    return True
                else:

                    time.sleep(2)  # Wait a bit before retrying
        except (Timeout, ConnectionError) as e:
            logging.info(f"Exception while fetching contract info: {e}. Retrying...")
            time.sleep(10)  # Wait a bit before retrying

    logging.info(f"Failed to verify contract after {retries} attempts. Marking as unverified.")
    return False


def is_erc20_compliant(token_abi):
    # Liste der erforderlichen ERC20-Funktionen
    required_functions = {item['name'] for item in ERC20_ABI if item['type'] == 'function'}

    # Überprüfung, ob die abgerufene ABI alle erforderlichen Funktionen enthält
    for item in token_abi:
        if item['type'] == 'function':
            try:
                required_functions.remove(item['name'])
            except KeyError:
                pass

    # Wenn alle erforderlichen Funktionen gefunden wurden, return True
    if not required_functions:
        return True

    # Wenn nicht alle erforderlichen Funktionen gefunden wurden, return False
    return False


def get_token_abi(token_address, is_bsc=False):
    # Überprüfen Sie, ob die ABI bereits lokal gespeichert ist
    if token_address in local_erc20_abi:
        return local_erc20_abi[token_address]

    # Andernfalls versuchen Sie, die ABI von der API zu erhalten
    if is_bsc:
        base_url = "https://api.bscscan.com"
        api_key = "4I9ZTHBDPQCSTI1JD9KNZSABZ9FY5CJKHS"
    else:
        base_url = "https://api.etherscan.io"
        api_key = "U7NDP99ZNMCKW7AH5PWC7CFMKBI81BBC35"

    url = f"{base_url}/api?module=contract&action=getabi&address={token_address}&apikey={api_key}"

    retry_count = 0
    response = None
    while retry_count < 3:
        try:
            response = requests.get(url)
            response_json = response.json()

            if response_json["status"] == "1" and response_json["result"]:
                token_abi = json.loads(response_json["result"])

                # Log successful fetch
                print(f"Successfully fetched ABI for token {token_address}.")

                # Überprüfe, ob die abgerufene ABI ERC20-konform ist
                if not is_erc20_compliant(token_abi):
                    logging.warning(f"The ABI for token address {token_address} is not fully ERC20-compliant")

                # Speichern Sie die ABI lokal für zukünftige Verwendung
                local_erc20_abi[token_address] = token_abi
                return token_abi
            else:
                logging.error(f"Failed to fetch ABI for token address {token_address}. Response: {response_json}")
                retry_count += 1
                time.sleep(3)
        except Exception as e:
            logging.error(
                f"Exception while fetching ABI: {e}. Response: {response.text if response else 'No response'}")

    logging.warning(f"Failed to fetch ABI for token address {token_address} after multiple attempts. Using standard ERC20_ABI instead.")
    return ERC20_ABI


def update_unverified_tokens(router_address):
    while True:
        for token_info in verifying_tokens[:]:  # Use a copy for iteration
            token_address = token_info["token_address"]
            pair_address = token_info["pair_address"]
            print(f"Checking if token {token_address} is verified.")
            if is_contract_verified(token_address, is_bsc=True):
                token_abi = get_token_abi(token_address, is_bsc=True)
                if token_abi:
                    local_erc20_abi[token_address] = token_abi
                    verifying_tokens.remove(token_info)
                    print(f"Token at {token_address} has been verified and removed from the verifying list.")
                    print(f"Token at {token_address} added to the newly_listed_not_tradable_pairs list.")
                    newly_listed_not_tradable_pairs.append(token_info)
                else:
                    logging.info(
                        f"Token at {token_address} could not be verified and stays in the verifying tokens list.")
            time.sleep(60)


def update_token_abi(token_addresses):
    token_abi_dict = {}
    for token_address in token_addresses:
        token_abi = get_token_abi(token_address)
        if token_abi:
            token_abi_dict[token_address] = token_abi
    return token_abi_dict


def get_pair_abi(pair_address, is_bsc=False):
    return get_token_abi(pair_address, is_bsc)


def get_token_contract(token_address, web3, is_bsc=False):
    token_abi = get_token_abi(token_address, is_bsc)
    if token_abi is not None:
        token_contract = web3.eth.contract(address=token_address, abi=token_abi)
        return token_contract
    else:
        logging.info(f"Could not get ABI for token address: {token_address}")
        return None

def get_factory(chain_id):
    if chain_id == 1:  # Ethereum
        # Uniswap Factory address
        factory_address = "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f"
    elif chain_id == 56:  # Binance Smart Chain
        # PancakeSwap Factory address
        factory_address = "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"
    else:
        raise ValueError("Unsupported chain_id")
    return factory_address


def get_weth_address(chain_id):
    if chain_id == 1:  # Ethereum
        return "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
    elif chain_id == 56:  # Binance Smart Chain
        return "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
    else:
        raise ValueError("Unsupported chain_id")


def get_platform(chain_id):
    if chain_id == 1:  # Ethereum
        return "uniswap"
    elif chain_id == 56:  # Binance Smart Chain
        return "pancakeswap"
    else:
        raise ValueError("Unsupported chain_id")


def get_token_info(token_address, is_bsc=False):
    token_abi = get_token_abi(token_address, is_bsc)
    if not token_abi:
        return None

    if is_bsc:
        web3 = web3_bsc
    else:
        web3 = web3_eth

    token_contract = web3.eth.contract(address=token_address, abi=token_abi)
    token_name = token_contract.functions.name().call()
    token_symbol = token_contract.functions.symbol().call()
    token_decimals = token_contract.functions.decimals().call()
    token_total_supply = token_contract.functions.totalSupply().call()

    token_info = {
        "name": token_name,
        "symbol": token_symbol,
        "decimals": token_decimals,
        "total_supply": token_total_supply,
        "contract_address": token_address,
    }

    return token_info


TELEGRAM_API = "6152865670:AAEhZ30YKVXOxDt-_HngNgNXsikqkDrjZEw"

updater = Updater(token=TELEGRAM_API, use_context=True)

bot = updater.bot
telegram_chat_id = "5081796381"

monitoring_uniswap = False
monitoring_pancakeswap = False

monitor_uniswap_pools_thread = None
monitor_pancakeswap_pools_thread = None


def your_telegram_handler(update: Update, context: CallbackContext):
    # Extrahieren Sie die Nachricht und deren Argumente
    message_text = update.message.text
    message_args = message_text.split(" ")

    if len(message_args) < 2:
        update.message.reply_text("Bitte geben Sie die erforderlichen Argumente an.")
        return

    platform = message_args[1]

    if platform == "uniswap":
        start_uniswap(update, context)
    elif platform == "pancakeswap":
        start_pancakeswap(update, context)




def get_infinite_unix_time():
    return int(datetime.datetime(2038, 1, 19).timestamp())


def check_token_tradeability(token_address, router_address):
    print(f"Checking tradeability for token {token_address} with router {router_address}")
    web3 = Web3(Web3.HTTPProvider(web3_provider))
    # Convert the router_address to checksum address
    router_address = web3.to_checksum_address(router_address)
    router_contract = web3.eth.contract(address=router_address, abi=uniswap_router_abi)

    # Simulate buying the token
    buy_path = [weth_address, token_address]
    buy_amount_in = web3.to_wei(0.1, 'ether')

    try:
        # Simulate buying
        buy_results = router_contract.caller.swapExactETHForTokens(0, buy_path, user_address,
                                                                   get_infinite_unix_time())

    except Exception as e:
        print(f"The token {token_address} is not tradeable: {e}")
        return False  # ändern Sie dies zu False statt "error"

    if buy_results[1] == 0:
        print(f"The token {token_address} is not tradeable.")
        return False

    print(f"Buying results: You will get {buy_results[1]} tokens for {buy_amount_in} Ether.")

    # Simulate selling the token
    sell_path = [token_address, weth_address]
    sell_amount_in = buy_results[1]

    try:
        # Simulate selling
        sell_results = router_contract.caller.swapExactTokensForETH(sell_amount_in, 0, sell_path, user_address, get_infinite_unix_time())

    except Exception as e:
        print(f"The token {token_address} is not tradeable: {e}")
        return False

    if sell_results[1] == 0:
        print(f"The token {token_address} is not sellable.")
        return False

    print(f"Selling results: You will get {sell_results[1]} Ether for {sell_amount_in} tokens.")

    # Calculate the tax or fee on the transaction
    tax_or_fee = (buy_amount_in - sell_results[1]) / buy_amount_in * 100

    # Check if the tax or fee is below the specified limit (should be less than 20% to get 80% back)
    tradeable = tax_or_fee <= 20
    if tradeable:
        print(f"The token {token_address} is tradeable.")
        return True
    else:
        print(f"The token {token_address} is not tradeable. The tax or fee is above the limit.")
        return False


def main():
    pancakeswap_config = {
        "chain_id": 56,
        "platform": "Pancakeswap",
        "router_address": "0x10ED43C718714EB63D5AA57B78B54704E256024E"
    }

    active_platform_config = pancakeswap_config

    monitor_pancakeswap_pools_thread = threading.Thread(
        target=monitor_pancakeswap_pools,
        args=(active_platform_config, web3_bsc, web3_eth)
    )
    monitor_pancakeswap_pools_thread.start()

    uniswap_config = {
        "chain_id": 1,
        "platform": "Uniswap",
        "router_address": "0x7A250D5630B4CF539739DF2C5DACB4C659F2488D"
    }

    active_platform_config = uniswap_config

    monitor_uniswap_pools_thread = threading.Thread(
        target=monitor_uniswap_pools,
        args=(active_platform_config, web3_eth)
    )
    monitor_uniswap_pools_thread.start()




def get_gas_price_from_oracle(chain="eth"):

    eth_api_key = "U7NDP99ZNMCKW7AH5PWC7CFMKBI81BBC35"
    bsc_api_key = "4I9ZTHBDPQCSTI1JD9KNZSABZ9FY5CJKHS"

    if chain == "eth":
        url = f"https://api.etherscan.io/api?module=proxy&action=eth_gasPrice&apikey={eth_api_key}"
    elif chain == "bsc":
        url = f"https://api.bscscan.com/api?module=proxy&action=eth_gasPrice&apikey={bsc_api_key}"
    else:
        print("Error: Invalid chain specified")
        return None

    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        print(data)
        gas_price = int(data["result"], 16)
        return gas_price

    else:
        print(f"Error: Unable to fetch gas price from {chain.upper()} oracle")
        return None


eth_gas_price = get_gas_price_from_oracle(chain="eth")
bsc_gas_price = get_gas_price_from_oracle(chain="bsc")

print("ETH gas price:", eth_gas_price)
print("BSC gas price:", bsc_gas_price)

web3_eth = Web3(
    Web3.HTTPProvider("https://eth-mainnet.g.alchemy.com/v2/7jSvlZt1FLEfOxQBadrQb93cMGmLyqjN")
)



def set_purchase_amount_uniswap(update: Update, context: CallbackContext):
    global purchase_amount_uniswap
    # Der zweite Textteil ist der Betrag in ETH
    amount = update.message.text.split(" ")[1]
    purchase_amount_uniswap = float(amount)
    update.message.reply_text(
        f"Die Kaufmenge für Uniswap wurde auf {amount} ETH festgelegt."
    )


def set_purchase_amount_pancakeswap(update: Update, context: CallbackContext):
    global purchase_amount_pancakeswap
    # Der zweite Textteil ist der Betrag in BNB
    amount = update.message.text.split(" ")[1]
    purchase_amount_pancakeswap = float(amount)
    update.message.reply_text(
        f"Die Kaufmenge für PancakeSwap wurde auf {amount} BNB festgelegt."
    )


def get_pending_transactions_from_sender(sender_address):
    pending_transactions_url = f"https://api.etherscan.io/api?module=account&action=txlist&address={sender_address}&startblock=0&endblock=pending&sort=asc&apikey=YOUR_API_KEY"

    response = requests.get(pending_transactions_url)
    if response.status_code == 200:
        json_data = response.json()
        return json_data["result"]

    return []


def monitor_liquidity_removal(
    token_pair_contract,
    token_contract,
    chain_id,
):
    latest_block = web3_eth.eth.block_number
    liquidity_removed_filter = token_pair_contract.events.LiquidityRemoved.createFilter(
        fromBlock=latest_block
    )
    developer_address = token_contract.functions.owner().call()

    while True:
        new_entries = liquidity_removed_filter.get_new_entries()
        pending_transactions = get_pending_transactions_from_sender(developer_address)

        # Analysiere die Transaktionen im Mempool
        for tx in pending_transactions:
            if tx["to"] == token_pair_contract.address:
                # Überprüfen Sie, ob der Entwickler versucht, Liquidität zu entfernen
                function_signature = web3_eth.to_bytes(hexstr=tx["input"][:10])
                if (
                    function_signature
                    == token_pair_contract.functions.removeLiquidity.__code_signature__
                ):
                    # Holen Sie sich die Menge der Liquidität, die entfernt wird
                    liquidity_to_remove = int(tx["input"][74:138], 16)

                    total_liquidity = token_pair_contract.functions.getReserves().call()[
                        0
                    ]  # Achten Sie darauf, den richtigen Index zu verwenden, abhängig von der Tokenposition im Paar
                    liquidity_percentage_removed = liquidity_to_remove / total_liquidity

                    if liquidity_percentage_removed > 0.10:
                        print(
                            "dev try to rug or dev try to sell more than 10% of lp."
                        )
                        success = sell_token_dynamic(
                            token_contract,
                            chain_id,
                            user_address,
                            sell_reason="liquidity_removal",
                        )
                        if success:
                            print("Token sold becouse of rug.")
                        else:
                            print("selling not possible")

        time.sleep(1)  # Überprüfe alle 1 Sekunden auf neue Ereignisse.

    # Gaspreis- und Slippage-Einstellungen basierend auf der Chain-ID


def is_suspicious(
    data, token_contract, token_contract_address, w3
):

    # Implement your custom logic to determine if a transaction is suspicious
    try:
        original_sell_amount = token_contract.functions.getAmountOut(
            1, user_address
        ).call()
        simulated_tx_result = w3.eth.call({"to": token_contract_address, "data": data})
        updated_contract = w3.eth.contract(
            address=token_contract_address, abi=token_contract.abi, bytecode=simulated_tx_result
        )
        updated_sell_amount = updated_contract.functions.getAmountOut(
            1, user_address
        ).call()
        if updated_sell_amount < original_sell_amount * 0.8:
            return True
    except Exception as e:
        print(f"Error simulating transaction: {e}")
    return False


def detect_suspicious_tx(
    token_pair_contract,
    token_address,
    token_contract,
    chain_id,
    w3,
):
    latest_block = w3.eth.block_number
    pending_tx_filter = w3.eth.filter("pending")

    while True:
        pending_transactions = pending_tx_filter.get_new_entries()

        # Analysiere die Transaktionen im Mempool
        for tx_hash in pending_transactions:
            tx = w3.eth.get_transaction(tx_hash)
            if tx["to"] == token_pair_contract.address:
                # Überprüfen Sie, ob die Transaktion verdächtig ist
                data = tx["input"]
                if is_suspicious(
                    data,
                    token_contract,
                    token_pair_contract.address,
                    w3,
                ):
                    success, tx_hash = sell_token_dynamic(
                        token_address,
                        token_contract,
                        chain_id,
                        sell_reason="Detect Suspicious TX",
                    )

                    if success:
                        print("Token sold becouse of suspicious tx.")
                    else:
                        print("Tokenverkauf fehlgeschlagen nach mehreren Versuchen")
                        if is_token_unsellable(token_contract):
                            print("Token not sellable.")
                            break

        time.sleep(1)  # Überprüfe alle 2 Sekunden auf neue Transaktionen.


def is_token_unsellable(token_contract, ):
    try:
        sell_amount = token_contract.functions.getAmountOut(1, user_address).call()
        if sell_amount == 0:
            return True
    except Exception as e:
        print(f"Error checking sell amount: {e}")
    return False



def get_router_contract(is_bsc=False, web3=None):
    if web3 is None:
        web3 ="https://eth-mainnet.g.alchemy.com/v2/7jSvlZt1FLEfOxQBadrQb93cMGmLyqjN"

    if is_bsc:
        router_address = "0x05fF2B0DB69458A0750badebc4f9e13aDd608C7F"  # BSC PancakeSwap router address
    else:
        router_address = "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D"  # Ethereum Uniswap router address

    router_abi = get_router_abi(router_address, is_bsc)

    router_contract = web3.eth.contract(address=router_address, abi=router_abi)
    return router_contract


def approve_token_purchase(token_contract, router_contract, user_address, private_key, amount, web3, chain_id):
    try:
        nonce = web3.eth.get_transaction_count(user_address)
        txn_dict = token_contract.functions.approve(router_contract.address, amount).buildTransaction({
            'chainId': chain_id,
            'gas': 500000,
            'gasPrice': web3.toWei('20', 'gwei'),
            'nonce': nonce,
        })

        signed_txn = web3.eth.account.sign_transaction(txn_dict, private_key=private_key)
        txn_hash = web3.eth.send_raw_transaction(signed_txn.rawTransaction)

        return txn_hash
    except Exception as e:
        print(f"An error occurred while approving token purchase: {str(e)}")
        return None


token_info = {}

def get_buy_slippage():
    return 0.30  # 30% Kaufslippage

MAX_BUY_RETRIES = 3

def buy_token(web3, platform_config):
    global user_address, private_key, purchase_amount_uniswap, purchase_amount_pancakeswap
    token_address = platform_config["token_address"]
    chain_id = platform_config["chain_id"]
    platform = platform_config["platform"]
    platform = get_platform(chain_id)

    if platform == "uniswap":
        purchase_amount = purchase_amount_uniswap
        is_bsc = False
    elif platform == "pancakeswap":
        purchase_amount = purchase_amount_pancakeswap
        is_bsc = True
    else:
        raise ValueError("Unknown platform")

    # Berechnung der Slippage
    buy_slippage = get_buy_slippage()

    # Ermittlung des Gaspreises aus dem Gas-Orakel
    gas_price = get_gas_price_from_oracle()

    max_gas_price = (
        MAX_GAS_PRICE_ETH
        if platform == "uniswap"
        else MAX_GAS_PRICE_BSC
    )

    if gas_price > max_gas_price:
        # Beenden der Schleife, wenn der maximale Gaspreis erreicht ist
        print("Maximaler Gaspreis erreicht.")
        return False

    print("versuche nun zu kaufen.")
    retries = 3

    # Get router contract and web3 instance
    router_contract = get_router_contract(is_bsc=is_bsc, web3=web3)

    # Get token contract
    token_contract = web3.eth.contract(address=token_address, abi=get_token_abi(token_address, is_bsc))

    while retries < MAX_BUY_RETRIES:
        try:
            # Approve token purchase
            approve_token_purchase(token_contract, router_contract, user_address, private_key,
                                   web3.to_wei(purchase_amount, 'ether'), web3, chain_id)

            # Buy token
            path = [weth_address, token_address]
            deadline = int(time.time()) + 300  # Using a deadline of 5 minutes
            txn_dict = router_contract.functions.swapExactETHForTokens(0,  # Minimum amount of tokens to buy
                                                                       path,
                                                                       user_address,
                                                                       deadline
                                                                       ).buildTransaction({
                'from': user_address,
                'value': web3.to_wei(purchase_amount, 'ether'),
                'gas': 250000,
                'gasPrice': web3.to_wei('20', 'gwei'),
                'nonce': web3.eth.get_transaction_count(user_address),
            })

            signed_txn = web3.eth.account.sign_transaction(txn_dict, private_key=private_key)
            txn_hash = web3.eth.send_raw_transaction(signed_txn.rawTransaction)
            print(f"Transaction {txn_hash.hex()} sent.")

            # Kaufpreis in ETH/BNB speichern
            buy_price = purchase_amount

            token = get_token_info(token_address, platform == "pancakeswap")
            amount_in_dollars = purchase_amount
            token_name = token["name"]
            token_symbol = token["symbol"]

            if platform == "uniswap":
                token_bought_with = "ETH"
            elif platform == "pancakeswap":
                token_bought_with = "BNB"
            else:
                token_bought_with = "Unknown"

            tx_receipt = web3_eth.eth.wait_for_transaction_receipt(txn_hash, timeout=300)
            transaction_hash = tx_receipt["transactionHash"].hex()

            message = (
                f"Kauf von {token_name} ({token_symbol}):\n"
                f"Menge {token_bought_with}: {purchase_amount}\n"
                f"Token gekauft mit: {token_bought_with}\n"
                f"Tx-Hash: {transaction_hash}\n"
            )

            bot.send_message(chat_id=telegram_chat_id, text=message)

            return True

        except Exception as e:
            # Fehler beim Kauf des Tokens
            print(f"Fehler beim Kauf des Tokens: {str(e)}")

            retries += 1
            time.sleep(1)
            continue

    print("Kauf des Tokens nach mehreren Versuchen nicht möglich.")
    return False


def buy_and_monitor_token(platform_config, web3):
    token_address = platform_config["token_address"]
    chain_id = platform_config["chain_id"]
    platform = platform_config["platform"]

    token_contract = get_token_contract(token_address, web3)

    # Check ob das Contract erfolgreich erstellt wurde
    if token_contract is None:
        print("Konnte kein Vertrag für das Token erstellt werden")
        return False
    print("Rufe buy funktion auf")
    token_purchase_successful = buy_token(
        web3, platform_config,
    )

    # Wenn der Kauf des Tokens nicht erfolgreich war, kehren Sie sofort aus der Funktion zurück
    if not token_purchase_successful:
        print("Kauf des Tokens fehlgeschlagen. Beende Funktion.")
        return False

    if chain_id == 1:  # Ethereum
        pair_address = uniswap_factory.functions.getPair(
            token_address, weth_address
        ).call()
    elif chain_id == 56:  # Binance Smart Chain
        pair_address = pancakeswap_factory.functions.getPair(
            token_address, weth_address
        ).call()
    else:
        raise ValueError("Unsupported chain_id")

    # Überwachen Sie die Liquiditätsentnahme für das neu gekaufte Paar
    token_pair_contract = get_token_contract(pair_address, web3)

    # Check ob das Contract erfolgreich erstellt wurde
    if token_pair_contract is None:
        print("Konnte kein Vertrag für das Token Paar erstellt werden")
        return False
    print("Rufe monitor_liquidity_removal funktion auf")
    monitor_thread = threading.Thread(
        target=monitor_liquidity_removal,
        args=(
            token_pair_contract,
            token_contract,
            chain_id,
        )
    )
    monitor_thread.start()
    print("Rufe detect_suspicious_tx funktion auf")
    # Fügen Sie hier den Thread für die Funktion detect_suspicious_tx hinzu
    detect_suspicious_tx_thread = threading.Thread(
        target=detect_suspicious_tx,
        args=(
            token_pair_contract,
            token_contract,
            chain_id,
            web3,
        )
    )
    detect_suspicious_tx_thread.start()

    # Return True am Ende der Funktion, wenn alles erfolgreich war
    return True




def monitor_uniswap_pools(platform_config, web3_eth):
    chain_id = platform_config["chain_id"]
    platform = platform_config["platform"]
    router_address = platform_config["router_address"]

    if router_address not in ["0x7A250D5630B4CF539739DF2C5DACB4C659F2488D",
                              "0x10ED43C718714EB63D5AA57B78B54704E256024E"]:
        logging.info(f"Ungültige Router-Adresse: {router_address}")
        return

    factory_address = Web3.to_checksum_address(get_factory(chain_id))
    uniswap_factory = web3_eth.eth.contract(address=factory_address, abi=uniswap_factory_abi)

    latest_block = web3_eth.eth.get_block('latest')['number']
    pair_created_filter = uniswap_factory.events.PairCreated.create_filter(fromBlock=latest_block)

    global monitoring_uniswap
    if monitoring_uniswap:
        print(f"Monitoring {platform} pools start")

    while monitoring_uniswap:
        new_entries = pair_created_filter.get_new_entries()
        if new_entries:
            print(f"New entries found: {new_entries}")
            for entry in new_entries:
                token1 = entry.args.token0
                token2 = entry.args.token1
                pair_address = entry.args.pair

                token1_abi = get_token_abi(token1, is_bsc=False)
                token2_abi = get_token_abi(token2, is_bsc=False)

                token1_contract = web3_eth.eth.contract(address=token1, abi=token1_abi)
                token2_contract = web3_eth.eth.contract(address=token2, abi=token2_abi)

                latest_block = web3_bsc.eth.get_block('latest')['number']
                pair_created_filter = pancakeswap_factory.events.PairCreated.create_filter(fromBlock=latest_block)

                logging.info(f"Token 1: {token1}, Token 2: {token2}, Pair Address: {pair_address}")

                tradeable = check_token_tradeability(
                    token1,
                    router_address,
                )
                logging.info(f"Token 1 is tradeable: {tradeable}")
                if tradeable:
                    buy_and_monitor_token(
                        token1,
                        chain_id,
                        platform,
                        web3_eth,
                        user_address,

                    )

                time.sleep(2)

    print(f"Beenden der Überwachung der {platform}-Pools.")


def monitor_pancakeswap_pools(platform_config, web3_bsc, web3_eth):
    chain_id = platform_config["chain_id"]
    platform = platform_config["platform"]
    router_address = platform_config["router_address"]
    web3 = web3_bsc if chain_id == 56 else web3_eth
    is_bsc = True if chain_id == 56 else False
    if router_address not in ["0x7A250D5630B4CF539739DF2C5DACB4C659F2488D",
                              "0x10ED43C718714EB63D5AA57B78B54704E256024E"]:
        logging.info(f"Ungültige Router-Adresse: {router_address}")
        return

    factory_address = Web3.to_checksum_address(get_factory(chain_id))
    pancakeswap_factory = web3.eth.contract(address=factory_address, abi=pancakeswap_factory_abi)

    latest_block = web3.eth.get_block('latest')['number']
    pair_created_filter = pancakeswap_factory.events.PairCreated.create_filter(fromBlock=latest_block)

    monitoring_pancakeswap = True
    if monitoring_pancakeswap:
        print(f"Monitoring {platform} pools start")

    update_thread = threading.Thread(target=update_unverified_tokens, args=(router_address,), daemon=True)
    update_thread.start()

    while monitoring_pancakeswap:
        new_entries = pair_created_filter.get_new_entries()

        if new_entries:
            print(f"New entries found: {new_entries}")

            for entry in new_entries:
                token0 = entry.args.token0
                token1 = entry.args.token1
                pair_address = entry.args.pair

                # Skip BNB and USDT
                if token0 in ['0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c',
                              '0x55d398326f99059fF775485246999027B3197955']:
                    token_to_check = token1
                elif token1 in ['0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c',
                                '0x55d398326f99059fF775485246999027B3197955']:
                    token_to_check = token0
                else:
                    token_to_check = None  # Or whichever default value makes sense for your use case

                # If token_to_check is None, both tokens were BNB or USDT and you might want to skip to the next iteration
                if token_to_check is None:
                    continue
                token_info = {"token_address": token_to_check, "pair_address": pair_address}
                platform_config["token_address"] = token_to_check
                # Check if the contract is verified
                if is_contract_verified(token_to_check, is_bsc):
                    token_abi = get_token_abi(token_to_check, is_bsc=True)
                    if token_abi:
                        local_erc20_abi[token_to_check] = token_abi
                        print(f"Token at {token_to_check} is already verified.")
                        print(f"Token at {token_to_check} added to the newly_listed_not_tradable_pairs list.")
                        newly_listed_not_tradable_pairs.append(token_info)
                    else:  # token_abi ist None
                        verifying_tokens.append(token_info)
                        print(
                            f"Token at {token_to_check} could not be verified and has been added to the verifying tokens list.")
                else:
                    verifying_tokens.append(token_info)
                    print(f"Unverified token {token_to_check} added to the verifying tokens list.")

                display_verifying_tokens()
                time.sleep(1)


def monitor_trading_start(web3, platform_config):
    global monitoring_pancakeswap
    global monitoring_uniswap
    global waiting_for_successful_swap
    global newly_listed_not_tradable_pairs
    global reported_tokens

    monitoring = None
    router_address = platform_config["router_address"]

    # Check which platform to monitor
    if platform_config["platform"] == "pancakeswap":
        monitoring = monitoring_pancakeswap
        print(f"Monitoring Pancakeswap")
    elif platform_config["platform"] == "Uniswap":
        monitoring = monitoring_uniswap
        print(f"Monitoring Uniswap")
    else:
        logging.error("Invalid platform")
        return

    while monitoring:
        for token_info in newly_listed_not_tradable_pairs:
            token_address = token_info["token_address"]
            pair_address = token_info["pair_address"]

            if token_address not in reported_tokens:
                reported_tokens[token_address] = True

            try:
                reserves = web3.eth.call(
                    {
                        "to": pair_address,
                        "data": '0x0902f1ac',
                    }
                )
            except Exception as e:
                logging.error(f"Error checking trading status: {str(e)}")
                continue

            if reserves != b"":
                print(
                    f"Trading started for token {token_address} at pair address {pair_address}"
                )

                tradeable = check_token_tradeability(token_address, router_address)
                print(f"Token {token_address} is tradeable: {tradeable}")

                # Call the check_token_tradeability function to check if the token is tradable
                if tradeable:
                    # Remove the pair from the list
                    newly_listed_not_tradable_pairs.remove(token_info)
                    print(
                        f"Token {token_address} removed from newly_listed_not_tradable_pairs list "
                    )
                else:
                    waiting_for_successful_swap.append(token_info)
                    print(
                        f"Token {token_address} added to the waiting for successful swap list"
                    )

            time.sleep(1)  # Check trading status every 60 seconds


list_lock = threading.Lock()


def monitor_successful_swap(web3, platform_config):
    global waiting_for_successful_swap
    global still_not_tradable
    global still_not_tradable_check_info

    router_address = platform_config["router_address"]
    block_type = 'latest'

    while True:
        with list_lock:
            waiting_list_copy = list(waiting_for_successful_swap)

        for token_info in waiting_list_copy:
            token_address = token_info["token_address"]
            pair_address = token_info["pair_address"]
            timestamp = token_info["timestamp"]

            if time.time() - timestamp > 2 * 24 * 60 * 60:
                with list_lock:
                    remove_from_list(token_info, waiting_for_successful_swap, 'waiting time exceeded 2 days')
                continue

            try:
                pair_abi = local_erc20_abi.get(token_address)
                if not pair_abi:
                    continue

                successful_swap = check_successful_swap(web3, pair_address, pair_abi, block_type)
                tradeable = check_token_tradeability(token_address, router_address)

                if tradeable and successful_swap:
                    with list_lock:
                        remove_from_list(token_info, waiting_for_successful_swap, 'token is tradable')

                if not tradeable:
                    with list_lock:
                        removed_token = remove_from_list(token_info, waiting_for_successful_swap,
                                                         'token is not tradable')
                        if removed_token is not None:
                            still_not_tradable.append(removed_token)
                            still_not_tradable_check_info[(token_address, pair_address)] = {
                                "wait_time": 60,
                                "checks": 0,
                                "last_check": time.time()
                            }

                    print(f"Trying to move token {token_address} - {pair_address} to still_not_tradable list...")
                    if token_info in still_not_tradable:
                        print(
                            f"Token pair {token_address} - {pair_address} successfully moved to still_not_tradable list.")
                    else:
                        print(f"Failed to move token pair {token_address} - {pair_address} to still_not_tradable list.")
            except Exception as e:
                print(f"Error in monitoring successful swap: {str(e)}")
                print("Waiting list:", [x["token_address"] for x in waiting_for_successful_swap])
                print("Still not tradable list:", [x["token_address"] for x in still_not_tradable])

            time.sleep(1)


def check_successful_swap(web3, pair_address, pair_abi, block_type):
    """
    This function checks for successful swaps based on block type.
    """

    # Get pair contract
    pair_contract = web3.eth.contract(address=pair_address, abi=pair_abi)
    print(f"Checking for successful swap for pair at address {pair_address}")

    # Create a filter for the "Swap" event based on block type
    swap_filter = pair_contract.events.Swap.createFilter(fromBlock=block_type)

    # Get new entries in the filter
    new_entries = swap_filter.get_new_entries()

    # If there are new entries in the filter, we return True
    if new_entries:
        print(f"Successful swap detected for pair at address {pair_address}")
        return True
    else:
        logging.info(f"No successful swap detected for pair at address {pair_address}")
        return False

# Funktion zum Überprüfen der Handelbarkeit und Durchführen eines Kaufs


# Funktion zum Überprüfen der Handelbarkeit und Durchführen eines Kaufs
def check_and_buy(web3, platform_config):
    global waiting_for_successful_swap
    global still_not_tradable
    global still_not_tradable_check_info

    router_address = platform_config["router_address"]
    token_address = platform_config["token_address"]

    tradeable = check_token_tradeability(token_address, router_address)
    if not tradeable:
        time.sleep(2)  # warte 2 Sekunden bevor erneut überprüft wird
        tradeable = check_token_tradeability(token_address, router_address)

    if tradeable:
        print(f"Token unter {token_address} ist jetzt handelbar. Beginne Kauf- und Überwachungssequenz.")
        purchase_successful = buy_and_monitor_token(platform_config, web3,)
        return purchase_successful
    else:
        # wenn der Token nicht handelbar ist, füge ihn sofort zur Liste "still_not_tradable" hinzu
        for token_info in waiting_for_successful_swap:
            if token_info["token_address"] == token_address:
                remove_from_list(token_info, waiting_for_successful_swap, 'token is not tradable')
                still_not_tradable.append(token_info)
                still_not_tradable_check_info[(token_address, token_info["pair_address"])] = {
                    "wait_time": 60,
                    "checks": 0,
                    "last_check": time.time()
                }
                print(f"Tokenpaar {token_address} - {token_info['pair_address']} wurde zur Liste 'still_not_tradable' hinzugefügt.")
                break

        return False


# Funktion zur Überwachung von nicht handelbaren Token
def monitor_still_not_tradable(web3, platform_config):
    global still_not_tradable
    global still_not_tradable_check_info

    router_address = platform_config["router_address"]

    while True:
        still_not_tradable_copy = list(still_not_tradable)
        for token_info in still_not_tradable_copy:
            token_address = token_info["token_address"]
            pair_address = token_info["pair_address"]

            check_info = still_not_tradable_check_info[(token_address, pair_address)]
            current_time = time.time()

            if check_info["last_check"] + check_info["wait_time"] <= current_time:
                tradeable = check_token_tradeability(token_address, router_address)

                if tradeable:
                    remove_from_list(token_info, still_not_tradable, 'token is now tradable')
                    del still_not_tradable_check_info[(token_address, pair_address)]
                else:
                    check_info["checks"] += 1
                    check_info["last_check"] = current_time

                    if check_info["checks"] % 2 == 0:
                        check_info["wait_time"] += 60

                    if check_info["checks"] >= 6:
                        remove_from_list(token_info, still_not_tradable, 'max checks reached')
                        del still_not_tradable_check_info[(token_address, pair_address)]

        time.sleep(1)



# Funktion zum Entfernen von Paaren aus Überwachungslisten
def remove_from_list(pair, list_name, reason):
    if pair in list_name:
        list_name.remove(pair)
        logging.info(f"Tokenpaar {pair} wurde aus der Liste {list_name} entfernt wegen {reason}.")
        return pair
    else:
        logging.info(f"Versuch, das Tokenpaar {pair} aus der Liste {list_name} zu entfernen, aber es wurde nicht gefunden.")
        return None




def start_uniswap(update: Update, context: CallbackContext):

    platform_config = {
        "chain_id": 1,
        "platform": "Uniswap",
        "router_address": "0x7A250D5630B4CF539739DF2C5DACB4C659F2488D"
    }

    global monitoring_uniswap
    global monitor_uniswap_pools_thread  # Zugriff auf den globalen Thread
    if not monitoring_uniswap:
        monitoring_uniswap = True
        update.message.reply_text(
            "Bot gestartet. Überwachung der Uniswap-Pools beginnt."
        )
        if (
            monitor_uniswap_pools_thread is None
            or not monitor_uniswap_pools_thread.is_alive()
        ):
            monitor_uniswap_pools_thread = threading.Thread(
                target=monitor_uniswap_pools,
                args=(platform_config, web3_eth)
            )

            monitor_uniswap_pools_thread.start()

            monitor_trading_start_thread = threading.Thread(
                target=monitor_trading_start,
                args=(web3_eth, platform_config)
            )
            monitor_trading_start_thread.start()
    else:
        update.message.reply_text("Uniswap-Überwachung läuft bereits.")

def stop_uniswap(update: Update, context: CallbackContext):
    global monitoring_uniswap
    if monitoring_uniswap:
        monitoring_uniswap = False
        update.message.reply_text(
            "Bot gestoppt. Überwachung der Uniswap-Pools beendet."
        )
    else:
        update.message.reply_text("Uniswap-Überwachung ist derzeit nicht aktiv.")
    time.sleep(3)
    if not monitoring_uniswap:
        print("Die Uniswap-Pool-Überwachung wurde erfolgreich gestoppt.")


def start_pancakeswap(update: Update, context: CallbackContext):
    platform_config = {
        "chain_id": 56,
        "platform": "pancakeswap",
        "router_address": "0x10ED43C718714EB63D5AA57B78B54704E256024E"
    }
    global monitoring_pancakeswap
    global monitor_pancakeswap_pools_thread  # Zugriff auf den globalen Thread
    if not monitoring_pancakeswap:
        monitoring_pancakeswap = True
        update.message.reply_text(
            "Bot gestartet. Überwachung der Pancakeswap-Pools beginnt."
        )
        if (
                monitor_pancakeswap_pools_thread is None
                or not monitor_pancakeswap_pools_thread.is_alive()
        ):
            monitor_pancakeswap_pools_thread = threading.Thread(
                target=monitor_pancakeswap_pools,
                args=(platform_config, web3_bsc, web3_eth)
            )
            monitor_pancakeswap_pools_thread.start()

            monitor_trading_start_thread = threading.Thread(
                target=monitor_trading_start,
                args=(web3_bsc, platform_config)
            )
            monitor_trading_start_thread.start()
    else:
        update.message.reply_text("Pancakeswap-Überwachung läuft bereits.")



def stop_pancakeswap(update: Update, context: CallbackContext):
    global monitoring_pancakeswap
    if monitoring_pancakeswap:
        monitoring_pancakeswap = False
        update.message.reply_text(
            "Bot gestoppt. Überwachung der Pancakeswap-Pools beendet."
        )
    else:
        update.message.reply_text("Pancakeswap-Überwachung ist derzeit nicht aktiv.")
    time.sleep(3)
    if not monitoring_pancakeswap:
        print("Die Pancakeswap-Pool-Überwachung wurde erfolgreich gestoppt.")







def check_pool_liquidity(
    factory_contract: Contract,
    pair_abi: list,
    token_address: str,
    liquidity_threshold: int,
    chain_id: int,
) -> bool:
    if chain_id == 1:  # Ethereum
        weth_address = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
    elif chain_id == 56:  # Binance Smart Chain
        weth_address = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
    else:
        raise ValueError("Unsupported chain_id")

    pair_address = factory_contract.functions.getPair(
        Web3.to_checksum_address(token_address), Web3.to_checksum_address(weth_address)
    ).call()

    if pair_address == "0x0000000000000000000000000000000000000000":
        return False

    pair_contract = web3_eth.eth.contract(address=pair_address, abi=pair_abi)
    reserves = pair_contract.functions.getReserves().call()
    liquidity = (
        reserves[0]
        if reserves[1] == Web3.to_checksum_address(token_address)
        else reserves[1]
    )

    return liquidity >= liquidity_threshold

def calculate_percentage_change_and_sort():
    sorted_token_info = {}
    for token_address, info in token_info.items():
        current_price = get_token_price(token_address, info["chain_id"])
        percentage_change = (
            (current_price - info["purchase_price"]) / info["purchase_price"]
        ) * 100
        info["percentage_change"] = percentage_change
        sorted_token_info[token_address] = info

    sorted_token_info = dict(
        sorted(
            sorted_token_info.items(),
            key=lambda item: item[1]["percentage_change"],
            reverse=True,
        )
    )
    return sorted_token_info


# Funktion zum Erstellen des Token-Listentexts
def generate_token_list_text(sorted_token_info, user_address):
    token_list_text = "Top 30 Token:\n\n"
    count = 0
    for token_info in sorted_token_info:
        if count >= 30:
            break

        token_address = token_info["token_address"]
        token_contract = web3_eth.eth.contract(address=token_address, abi=get_token_abi)

        # Überprüfen Sie das Token-Guthaben des Benutzers
        token_balance = token_contract.functions.balanceOf(user_address).call()
        if token_balance > 0:
            token_name = token_info["token_name"]
            percentage_change = token_info["percentage_change"]
            dexscreener_url = token_info["dexscreener_url"]
            token_list_text += f"{count + 1}. {token_name} - {percentage_change:.2f}% - [Chart]({dexscreener_url})\n"
            count += 1
    return token_list_text


def show_top_tokens(update: Update, context: CallbackContext):
    global telegram_chat_id
    telegram_chat_id = update.message.chat_id
    update.message.reply_text(
        "Die Liste der Top 30-Token wird automatisch alle 60 Sekunden aktualisiert."
    )
    auto_update_token_list_thread = threading.Thread(
        target=auto_update_token_list,
        args=(
            context.args[0],
            context.bot,
        ),  # Pass the bot instance to the function
    )
    auto_update_token_list_thread.start()


def auto_update_token_list(user_address):
    global telegram_chat_id
    bot = telegram.Bot(token=TELEGRAM_API)
    while telegram_chat_id:
        sorted_token_info = calculate_percentage_change_and_sort()
        token_list_text = generate_token_list_text(sorted_token_info, user_address)
        bot.send_message(
            chat_id=telegram_chat_id,
            text=token_list_text,
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
        time.sleep(20)


def get_token_price(token_address, chain_id):
    if chain_id == 1:  # Ethereum
        web3 = web3_eth
        weth_address = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
    elif chain_id == 56:  # Binance Smart Chain
        web3 = web3_bsc
        weth_address = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
    else:
        raise ValueError("Unsupported chain_id")

    token_pair_contract = get_token_pair_contract(token_address, web3)
    if token_pair_contract is None:
        return None

    token_reserve = token_pair_contract.functions.balanceOf(token_address).call()
    weth_reserve = token_pair_contract.functions.balanceOf(weth_address).call()
    token_decimals = token_pair_contract.functions.decimals().call()
    weth_decimals = 18

    token_price = (weth_reserve / (10**weth_decimals)) / (
        token_reserve / (10**token_decimals)
    )

    return token_price


def is_token_unsellable(token_contract, user_address):
    try:
        sell_amount = token_contract.functions.getAmountOut(1, user_address).call()
        if sell_amount == 0:
            return True
    except Exception as e:
        print(f"Error checking sell amount: {e}")
    return False


def sell_token_dynamic(
    token_contract,
    user_address,
    max_slippage,
    gas_price_increment,
    max_gas_price,
    chain_id,
    telegram_chat_id,
    uniswap_factory_abi=UNISWAP_FACTORY_ABI,
    uniswap_pair_abi=token_pair_abi,
    token_address=get_token_abi,
    sell_reason=None,
):
    # Überprüfen Sie, ob das Token-Guthaben Null ist
    global tx_hash, gas_price, slippage
    token_balance = token_contract.functions.balanceOf(user_address).call()
    if token_balance == 0:
        print("Keine Token mehr im Guthaben, Verkauf abgebrochen.")
        return False, None

    token = get_token_info(token_address, chain_id == 56)

    # Setzen Sie den Schwellenwert für die minimale Liquidität, die für den Verkauf erforderlich ist
    liquidity_threshold = 1

    if chain_id == 1:  # Ethereum
        factory_address = "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f"
    elif chain_id == 56:  # Binance Smart Chain
        factory_address = "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"
    else:
        raise ValueError("Unsupported chain_id")

    factory_contract = web3_eth.eth.contract(
        adress=factory_address, abi=uniswap_factory_abi
    )  # Uniswap or PancakeSwap factory contract

    while True:


        if chain_id == 1:
            factory_contract = uniswap_factory
        elif chain_id == 56:
            factory_contract = pancakeswap_factory
        else:
            raise ValueError("Unsupported chain_id")

        if not check_pool_liquidity(
            factory_contract,
            uniswap_pair_abi,
            token_contract.address,
            liquidity_threshold,
            chain_id,
        ):

            print("Liquidität im Pool zu niedrig, Verkauf abgebrochen.")
            return False

        if is_token_unsellable(token_contract, user_address):
            print("Token ist unverkäuflich, Verkauf abgebrochen.")
            return False, None

        MAX_RETRIES = 3

        success = False
        retries = 0
        while not success and retries < MAX_RETRIES:

                path = [token_address, weth_address[chain_id]]
                amountIn = token_balance
                amountOutMin = 0  # Hier setzen wir amountOutMin auf 0.
                deadline = web3_eth.eth.get_block("latest")["timestamp"] + 60
                data = token_contract.encodeABI(
                    fn_name="swapExactTokensForETHSupportingFeeOnTransferTokens",
                    args=[amountIn, amountOutMin, path, user_address, deadline],
                )

                txn = {
                    "nonce": web3_eth.eth.get_transaction_count(user_address),
                    "gasPrice": gas_price,
                    "gas": 1000000,
                    "to": token_address,
                    "data": data,
                    "value": 0,  # No ETH/BNB is being sent
                }

                # Signieren der Transaktion
                signed_tx = web3_eth.eth.account.signTransaction(txn, private_key)

                # Absenden der Transaktion
                tx_hash = web3_eth.eth.send_raw_transaction(signed_tx.rawTransaction)

                # Warten auf die Bestätigung der Transaktion
                web3_eth.eth.wait_for_transaction_receipt(tx_hash, timeout=300)

                # Überprüfen, ob die Transaktion erfolgreich war
                tx_receipt = web3_eth.eth.get_transaction_receipt(tx_hash)
                if tx_receipt["status"]:
                    success = True

        if not success:
            print(
                f"Tokenverkauf fehlgeschlagen, versuche es erneut mit {slippage * 100}% Slippage und {gas_price / 1000000000} Gwei Gaspreis"
            )
            retries += 1
            time.sleep(1)

        if success:
            # Berechnung des Verkaufspreises in ETH/BNB
            sold_amount = (
                token_contract.functions.balanceOf(user_address).call()
                / 10 ** token["decimals"]
            )
            sell_price = sold_amount

            # Kaufpreis holen
            buy_price = purchase_prices[token_contract.address]

            # Berechnung des Gewinns oder Verlusts in Prozent
            profit_loss_percent = ((sell_price - buy_price) / buy_price) * 100

            token = get_token_info(token_contract.address, chain_id == 56)
            sold_amount = (
                token_contract.functions.balanceOf(user_address).call()
                / 10 ** token["decimals"]
            )
            token_name = token["name"]
            token_symbol = token["symbol"]

            if chain_id == 1:
                sold_for = "ETH"
            elif chain_id == 56:
                sold_for = "BNB"
            else:
                sold_for = "Unknown"

            tx_receipt = web3_eth.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
            transaction_hash = tx_receipt["transactionHash"].hex()

            message = (
                f"Verkauf von {token_name} ({token_symbol}):\n"
                f"Menge {sold_for}: {sold_amount}\n"
                f"Token verkauft für: {sold_for}\n"
                f"Tx-Hash: {transaction_hash}\n"
                f"Gewinn/Verlust: {profit_loss_percent:.2f}%\n"
                f"Verkaufsgrund: {sell_reason}\n"
            )
            bot.send_message(chat_id=telegram_chat_id, text=message)

            return True, tx_hash
        else:
            return False, None




take_profit_targets_by_chain = {
    1: [200.0, 500.0],  # ETH Take-Profit-Ziele
    56: [100.0, 200.0],  # BNB Take-Profit-Ziele
}
purchase_prices = {}

def on_new_token_purchase(
    token_address,
    get_token_price,
    token_contract,
    user_adress,
    dynamic_slippage,
    gas_price_increment,
    max_gas_price,
    chain_id,
    chat_id,
    UNISWAP_FACTORY_ABI,
    token_pair_abi,
    sell_reason=None,
    token_abi=None,
):
    # Ersetzen Sie durch Ihre Infura-URL oder einen anderen Web3-Provider
    global success
    web3 = Web3(
        Web3.HTTPProvider(
            "https://mainnet.infura.io/v3/e5d07cea563b45deb401f98d21abf375"
        )
    )
    token_contract = web3.eth.contract(address=token_address, abi=token_abi)
    user_address = "0x67c80682Df8198b073c9E74908eFf94F9b5726Ab"

    # Setzen Sie Ihre Take-Profit-Ziele in % hier
    take_profit_targets = [100.0, 200.0]
    stop_loss_target = -60.0  # Setzen Sie Ihr Stop-Loss-Ziel in % hier
    amount_to_sell = 0
    take_profit_count = 0  # Initialisierung der Variable

    initial_price = get_token_price(token_address, chain_id)

    token_name = token_contract.functions.name().call()
    initial_token_balance = token_contract.functions.balanceOf(user_address).call()
    token_info[token_address] = {
        "name": token_name,
        "purchase_price": initial_price,
        "initial_balance": initial_token_balance,
        "chain_id": chain_id,
    }

    while True:
        token_balance = token_contract.functions.balanceOf(user_address).call()

        # Überprüfen Sie, ob ein Take-Profit-Ziel erreicht wurde
        current_price = get_token_price(token_address, chain_id)
        price_change_percentage = (
            (current_price - initial_price) / initial_price
        ) * 100

        take_profit_targets = take_profit_targets_by_chain.get(chain_id)

        for target_index, target in enumerate(take_profit_targets):
            if price_change_percentage >= target and amount_to_sell == 0:
                if target_index == 0:  # Wenn es das erste Take-Profit-Ziel ist
                    # Verkaufe 50% der Tokens beim ersten Take-Profit-Ziel
                    amount_to_sell = token_balance * 0.5
                    sell_reason = f"Take Profit {target_index + 1}"
                    print(
                        f"Take-Profit-Ziel von {target}% erreicht, verkaufe {amount_to_sell} Tokens..."
                    )
                    success = sell_token_dynamic(
                        token_address,
                        user_address,
                        dynamic_slippage,
                        gas_price_increment,
                        max_gas_price,
                        chain_id,
                        chat_id,
                        UNISWAP_FACTORY_ABI,
                        token_pair_abi,
                        sell_reason="Take Profit 1",
                    )
                elif target_index == 1:  # Wenn es das zweite Take-Profit-Ziel ist
                    # Verkaufe 50% der Tokens beim zweiten Take-Profit-Ziel
                    amount_to_sell = token_balance * 0.50
                    sell_reason = f"Take Profit {target_index + 1}"
                    print(
                        f"Take-Profit-Ziel von {target}% erreicht, verkaufe {amount_to_sell} Tokens..."
                    )
                    success = sell_token_dynamic(
                        token_address,
                        user_address,
                        dynamic_slippage,
                        gas_price_increment,
                        max_gas_price,
                        chain_id,
                        chat_id,
                        UNISWAP_FACTORY_ABI,
                        token_pair_abi,
                        sell_reason="Take Profit 2",
                    )

                if success:
                    print(f"{amount_to_sell} Tokens erfolgreich verkauft.")
                    take_profit_count += 1
                else:
                    print(f"Tokenverkauf fehlgeschlagen nach mehreren Versuchen")
                # Beenden Sie die Schleife, wenn alle Take-Profit-Ziele erreicht wurden
                if take_profit_count == len(take_profit_targets):
                    print("Alle Take-Profit-Ziele erreicht.")
                    break

        # Überprüfen Sie, ob das Stop-Loss-Ziel erreicht wurde
        if price_change_percentage <= stop_loss_target:
            sell_reason = "Stop Loss"
            print(
                f"Stop-Loss-Ziel von {stop_loss_target}% erreicht, verkaufe alle verbleibenden Tokens..."
            )
            success = sell_token_dynamic(
                token_address,
                user_address,
                dynamic_slippage,
                gas_price_increment,
                max_gas_price,
                chain_id,
                chat_id,
                UNISWAP_FACTORY_ABI,
                token_pair_abi,
                sell_reason="Stop Loss",
            )

            if success:
                print(f"Alle verbleibenden Tokens erfolgreich verkauft.")
            else:
                print(f"Tokenverkauf fehlgeschlagen nach mehreren Versuchen")
            break

        time.sleep(1)

        # Beenden Sie die Schleife, wenn alle Take-Profit-Ziele erreicht wurden
        if take_profit_count == len(take_profit_targets):
            print("Alle Take-Profit-Ziele erreicht.")
            break





def trading_bot():
    dispatcher = updater.dispatcher

    start_uniswap_handler = CommandHandler("start_uniswap", start_uniswap)
    start_pancakeswap_handler = CommandHandler("start_pancakeswap", start_pancakeswap)
    stop_uniswap_handler = CommandHandler("stop_uniswap", stop_uniswap)
    stop_pancakeswap_handler = CommandHandler("stop_pancakeswap", stop_pancakeswap)
    set_purchase_amount_uniswap_handler = CommandHandler(
        "set_purchase_amount_uniswap", set_purchase_amount_uniswap
    )
    set_purchase_amount_pancakeswap_handler = CommandHandler(
        "set_purchase_amount_pancakeswap", set_purchase_amount_pancakeswap
    )
    set_take_profit_targets_uniswap_handler = CommandHandler(
        "set_take_profit_targets_uniswap",
        set_take_profit_targets_uniswap,
    )
    set_take_profit_targets_pancakeswap_handler = CommandHandler(
        "set_take_profit_targets_pancakeswap",
        set_take_profit_targets_pancakeswap,
    )

    show_top_tokens_handler = CommandHandler("show_top_tokens", show_top_tokens)

    dispatcher.add_handler(start_uniswap_handler)
    dispatcher.add_handler(start_pancakeswap_handler)
    dispatcher.add_handler(stop_uniswap_handler)
    dispatcher.add_handler(stop_pancakeswap_handler)
    dispatcher.add_handler(set_purchase_amount_uniswap_handler)
    dispatcher.add_handler(set_purchase_amount_pancakeswap_handler)
    dispatcher.add_handler(set_take_profit_targets_uniswap_handler)
    dispatcher.add_handler(set_take_profit_targets_pancakeswap_handler)
    dispatcher.add_handler(show_top_tokens_handler)

    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    trading_bot()
