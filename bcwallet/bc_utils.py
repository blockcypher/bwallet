from bitmerchant.network import BitcoinMainNet
from bitmerchant.network import BitcoinTestNet
from bitmerchant.network import LitecoinMainNet
from bitmerchant.network import DogecoinMainNet
from bitmerchant.network import BlockCypherTestNet

from bitmerchant.wallet import Wallet

from blockcypher.utils import is_valid_coin_symbol, is_valid_hash, coin_symbol_from_mkey

# collection of blockchain/crypto utilities and helper methods

COIN_SYMBOL_TO_BMERCHANT_NETWORK = {
        'btc': BitcoinMainNet,
        'btc-testnet': BitcoinTestNet,
        'ltc': LitecoinMainNet,
        'doge': DogecoinMainNet,
        'bcy': BlockCypherTestNet,
        }


def guess_network_from_mkey(mkey):
    cs = next(iter(coin_symbol_from_mkey(mkey)))
    return COIN_SYMBOL_TO_BMERCHANT_NETWORK.get(cs)


def get_tx_url(tx_hash, coin_symbol):
    assert is_valid_coin_symbol(coin_symbol), coin_symbol
    assert is_valid_hash(tx_hash), tx_hash
    return 'https://live.blockcypher.com/%s/tx/%s/' % (coin_symbol, tx_hash)


def verify_and_fill_address_paths_from_bip32key(address_paths, master_key, network):
    '''
    Take address paths and verifies their accuracy client-side.

    Also fills in all the available metadata (WIF, public key, etc)
    '''

    assert network, network

    wallet_obj = Wallet.deserialize(master_key, network=network)

    address_paths_cleaned = []

    for address_path in address_paths:
        path = address_path['path']
        input_address = address_path['address']
        child_wallet = wallet_obj.get_child_for_path(path)

        if child_wallet.to_address() != input_address:
            err_msg = 'Client Side Verification Fail for %s on %s:\n%s != %s' % (
                    path,
                    master_key,
                    child_wallet.to_address(),
                    input_address,
                    )
            raise Exception(err_msg)

        pubkeyhex = child_wallet.get_public_key_hex(compressed=True)

        server_pubkeyhex = address_path.get('public')
        if server_pubkeyhex and server_pubkeyhex != pubkeyhex:
            err_msg = 'Client Side Verification Fail for %s on %s:\n%s != %s' % (
                    path,
                    master_key,
                    pubkeyhex,
                    server_pubkeyhex,
                    )
            raise Exception(err_msg)

        address_path_cleaned = {
            'pub_address': input_address,
            'path': path,
            'pubkeyhex': pubkeyhex,
            }

        if child_wallet.private_key:
            privkeyhex = child_wallet.get_private_key_hex()
            address_path_cleaned['wif'] = child_wallet.export_to_wif()
            address_path_cleaned['privkeyhex'] = privkeyhex
        address_paths_cleaned.append(address_path_cleaned)

    return address_paths_cleaned


def hexkeypair_list_to_dict(hexkeypair_list):
    hexkeypair_dict = {}
    for hexkeypair in hexkeypair_list:
        pub_address = hexkeypair['pub_address']
        hexkeypair.pop('pub_address')
        hexkeypair_dict[pub_address] = hexkeypair
    return hexkeypair_dict
