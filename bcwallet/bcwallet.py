# -*- coding: utf-8 -*-

import sys
import argparse
import pkg_resources
import traceback
import webbrowser

# just for printing
from clint.textui import puts, colored, indent

from bitmerchant.wallet import Wallet

from blockcypher.api import create_hd_wallet
from blockcypher.api import get_wallet_transactions
from blockcypher.api import get_wallet_addresses
from blockcypher.api import get_wallet_balance
from blockcypher.api import derive_hd_address
from blockcypher.api import create_unsigned_tx
from blockcypher.api import verify_unsigned_tx
from blockcypher.api import get_input_addresses
from blockcypher.api import make_tx_signatures
from blockcypher.api import broadcast_signed_transaction
from blockcypher.api import get_total_balance
from blockcypher.api import get_blockchain_overview

from blockcypher.utils import get_blockcypher_walletname_from_mpub
from blockcypher.utils import coin_symbol_from_mkey
from blockcypher.utils import format_crypto_units
from blockcypher.utils import from_satoshis
from blockcypher.utils import to_satoshis
from blockcypher.utils import flatten_txns_by_hash
from blockcypher.utils import get_curr_symbol
from blockcypher.utils import uses_only_hash_chars

from blockcypher.constants import COIN_SYMBOL_MAPPINGS

from .bc_utils import guess_network_from_mkey
from .bc_utils import verify_and_fill_address_paths_from_bip32key
from .bc_utils import get_tx_url
from .bc_utils import hexkeypair_list_to_dict
from .bc_utils import COIN_SYMBOL_TO_BMERCHANT_NETWORK

from .cl_utils import debug_print
from .cl_utils import choice_prompt
from .cl_utils import get_public_wallet_url
from .cl_utils import get_crypto_address
from .cl_utils import get_wif_obj
from .cl_utils import get_crypto_qty
from .cl_utils import get_int
from .cl_utils import confirm
from .cl_utils import get_user_entropy
from .cl_utils import coin_symbol_chooser
from .cl_utils import txn_preference_chooser
from .cl_utils import first4mprv_from_mpub
from .cl_utils import print_pubwallet_notice
from .cl_utils import print_traversal_warning
from .cl_utils import print_bcwallet_basic_priv_opening
from .cl_utils import print_bcwallet_piped_priv_opening
from .cl_utils import print_bcwallet_piped_priv_cat_opening
from .cl_utils import print_bcwallet_basic_pub_opening
from .cl_utils import print_childprivkey_warning
from .cl_utils import print_keys_not_saved
from .cl_utils import UNIT_CHOICES
from .cl_utils import BCWALLET_PRIVPIPE_EXPLANATION
from .cl_utils import BCWALLET_PRIVPIPE_CAT_EXPLANATION
from .cl_utils import BCWALLET_PIPE_ENCRYPTION_EXPLANATION
from .cl_utils import DEFAULT_PROMPT
from .cl_utils import EXPLAINER_COPY

from .version_checker import get_latest_bcwallet_version
from .version_checker import GITHUB_URL

from tzlocal import get_localzone

# Globals that can be overwritten at startup
VERBOSE_MODE = False
USER_ONLINE = False
BLOCKCYPHER_API_KEY = ''
UNIT_CHOICE = ''


def verbose_print(to_print):
    if VERBOSE_MODE:
        debug_print(to_print)


def is_connected_to_blockcypher():
    try:
        get_blockchain_overview()
        return True
    except Exception as e:
        verbose_print(e)
        return False


def display_balance_info(wallet_obj, verbose=False):
    if not USER_ONLINE:
        return

    mpub = wallet_obj.serialize_b58(private=False)

    wallet_name = get_blockcypher_walletname_from_mpub(
            mpub=mpub,
            subchain_indices=[0, 1],
            )

    verbose_print('Wallet Name: %s' % wallet_name)
    verbose_print('API Key: %s' % BLOCKCYPHER_API_KEY)

    coin_symbol = coin_symbol_from_mkey(mpub)

    wallet_details = get_wallet_balance(
            wallet_name=wallet_name,
            api_key=BLOCKCYPHER_API_KEY,
            coin_symbol=coin_symbol,
            )
    verbose_print(wallet_details)

    puts('-' * 70 + '\n')
    balance_str = 'Balance: %s' % (
            format_crypto_units(
                input_quantity=wallet_details['final_balance'],
                input_type='satoshi',
                output_type=UNIT_CHOICE,
                coin_symbol=coin_symbol,
                print_cs=True,
            ))
    puts(colored.green(balance_str))
    if wallet_details['unconfirmed_balance']:
        balance_str += ' (%s%s of this is unconfirmed)' % (
                '+' if wallet_details['unconfirmed_balance'] else '',  # hack
                format_crypto_units(
                    input_quantity=wallet_details['unconfirmed_balance'],
                    input_type='satoshi',
                    output_type=UNIT_CHOICE,
                    print_cs=True,
                    coin_symbol=coin_symbol,
                ),
                )

    tx_string = 'Transactions: %s' % wallet_details['final_n_tx']
    if wallet_details['unconfirmed_n_tx']:
        tx_string += ' (%s unconfirmed)' % wallet_details['unconfirmed_n_tx']
    puts(colored.green(tx_string + '\n'))

    puts('More info:')
    puts(colored.blue(get_public_wallet_url(mpub)))
    puts()

    return wallet_details['final_balance']


def get_addresses_on_both_chains(wallet_obj, used=None, zero_balance=None):
    '''
    Get addresses across both subchains based on the filter criteria passed in

    Returns a list of dicts of the following form:
        [
            {'address': '1abc123...', 'path': 'm/0/9', 'pubkeyhex': '0123456...'},
            ...,
        ]

    Dicts may also contain WIF and privkeyhex if wallet_obj has private key
    '''
    mpub = wallet_obj.serialize_b58(private=False)

    wallet_name = get_blockcypher_walletname_from_mpub(
            mpub=mpub,
            subchain_indices=[0, 1],
            )

    wallet_addresses = get_wallet_addresses(
            wallet_name=wallet_name,
            api_key=BLOCKCYPHER_API_KEY,
            is_hd_wallet=True,
            used=used,
            zero_balance=zero_balance,
            coin_symbol=coin_symbol_from_mkey(mpub),
            )
    verbose_print('wallet_addresses:')
    verbose_print(wallet_addresses)

    if wallet_obj.private_key:
        master_key = wallet_obj.serialize_b58(private=True)
    else:
        master_key = mpub

    chains_address_paths_cleaned = []
    for chain in wallet_addresses['chains']:
        if chain['chain_addresses']:
            chain_address_paths = verify_and_fill_address_paths_from_bip32key(
                    address_paths=chain['chain_addresses'],
                    master_key=master_key,
                    network=guess_network_from_mkey(mpub),
                    )
            chain_address_paths_cleaned = {
                    'index': chain['index'],
                    'chain_addresses': chain_address_paths,
                    }
            chains_address_paths_cleaned.append(chain_address_paths_cleaned)

    return chains_address_paths_cleaned


def register_unused_addresses(wallet_obj, subchain_index, num_addrs=1):
    '''
    Hit /derive to register new unused_addresses on a subchain_index and verify them client-side

    Returns a list of dicts of the following form:
        [
            {'address': '1abc123...', 'path': 'm/0/9', 'public': '0123456...'},
            ...,
        ]
    '''

    verbose_print('register_unused_addresses called on subchain %s for %s addrs' % (
        subchain_index,
        num_addrs,
        ))

    assert type(subchain_index) is int, subchain_index
    assert type(num_addrs) is int, num_addrs
    assert num_addrs > 0

    mpub = wallet_obj.serialize_b58(private=False)
    coin_symbol = coin_symbol_from_mkey(mpub)
    wallet_name = get_blockcypher_walletname_from_mpub(
            mpub=mpub,
            subchain_indices=[0, 1],
            )
    network = guess_network_from_mkey(mpub)

    # register new address(es)
    derivation_response = derive_hd_address(
            api_key=BLOCKCYPHER_API_KEY,
            wallet_name=wallet_name,
            num_addresses=num_addrs,
            subchain_index=subchain_index,
            coin_symbol=coin_symbol,
            )

    verbose_print('derivation_response:')
    verbose_print(derivation_response)

    address_paths = derivation_response['chains'][0]['chain_addresses']

    # verify new addresses client-side
    full_address_paths = verify_and_fill_address_paths_from_bip32key(
            address_paths=address_paths,
            master_key=mpub,
            network=network,
            )

    return full_address_paths


def get_unused_receiving_addresses(wallet_obj, num_addrs=1):

    return register_unused_addresses(
            wallet_obj=wallet_obj,
            subchain_index=0,  # external chain
            num_addrs=num_addrs,
            )


def get_unused_change_addresses(wallet_obj, num_addrs=1):
    return register_unused_addresses(
            wallet_obj=wallet_obj,
            subchain_index=1,  # internal chain
            num_addrs=num_addrs,
            )


def display_new_receiving_addresses(wallet_obj):

    if not USER_ONLINE:
        puts(colored.red('BlockCypher connection needed to see which addresses have been used.'))
        puts(colored.red('You may dump all your addresses offline by selecting option 0.'))
        return

    mpub = wallet_obj.serialize_b58(private=False)

    puts('How many receiving addreses keys do you want to see (max 5 at a time)?')
    puts('Enter "b" to go back.\n')

    num_addrs = get_int(
            user_prompt=DEFAULT_PROMPT,
            min_int=1,
            max_int=5,
            default_input='1',
            show_default=True,
            quit_ok=True,
            )

    if num_addrs is False:
        return

    verbose_print('num_addrs:\n%s' % num_addrs)

    unused_receiving_addresses = get_unused_receiving_addresses(
            wallet_obj=wallet_obj,
            num_addrs=num_addrs,
            )

    puts('-' * 70 + '\n')
    if num_addrs > 1:
        addr_str = 'Addresses'
    else:
        addr_str = 'Address'

    puts('Unused %s Receiving %s - (for others to send you funds):' % (
        COIN_SYMBOL_MAPPINGS[coin_symbol_from_mkey(mpub)]['currency_abbrev'],
        addr_str,
        ))

    for unused_receiving_address in unused_receiving_addresses:
        with indent(2):
            puts(colored.green('%s (path is %s)' % (
                unused_receiving_address['pub_address'],
                unused_receiving_address['path'],
                )))


def display_recent_txs(wallet_obj):
    if not USER_ONLINE:
        puts(colored.red('BlockCypher connection needed to find transactions related to your addresses.'))
        puts(colored.red('You may dump all your addresses while offline by selecting option 0.'))
        return

    local_tz = get_localzone()

    # Show overall balance info
    display_balance_info(wallet_obj=wallet_obj)

    mpub = wallet_obj.serialize_b58(private=False)
    wallet_name = get_blockcypher_walletname_from_mpub(
            mpub=mpub,
            subchain_indices=[0, 1],
            )

    wallet_details = get_wallet_transactions(
            wallet_name=wallet_name,
            api_key=BLOCKCYPHER_API_KEY,
            coin_symbol=coin_symbol_from_mkey(mpub),
            )
    verbose_print(wallet_details)

    # TODO: pagination for lots of transactions

    txs = wallet_details.get('unconfirmed_txrefs', []) + wallet_details.get('txrefs', [])

    if txs:
        for tx_object in flatten_txns_by_hash(txs, nesting=False):
            if tx_object.get('confirmed_at'):
                tx_time = tx_object['confirmed_at']
            else:
                tx_time = tx_object['received_at']
            net_satoshis_tx = sum(tx_object['txns_satoshis_list'])
            conf_str = ''
            has_confirmations = False
            if tx_object.get('confirmed_at'):
                if tx_object.get('confirmations'):
                    has_confirmations = True
                    if tx_object.get('confirmations') <= 6:
                        conf_str = ' (%s confirmations)' % tx_object.get('confirmations')
                    else:
                        conf_str = ' (6+ confirmations)'
            else:
                conf_str = ' (0 confirmations!)'
            print_str = '%s: %s%s %s in TX hash %s%s' % (
                    tx_time.astimezone(local_tz).strftime("%Y-%m-%d %H:%M %Z"),
                    '+' if net_satoshis_tx > 0 else '',
                    format_crypto_units(
                        input_quantity=net_satoshis_tx,
                        input_type='satoshi',
                        output_type=UNIT_CHOICE,
                        coin_symbol=coin_symbol_from_mkey(mpub),
                        print_cs=True,
                        ),
                    'received' if net_satoshis_tx > 0 else 'sent',
                    tx_object['tx_hash'],
                    conf_str,
                    )
            if has_confirmations:
                puts(colored.green(print_str))
            else:
                puts(colored.yellow(print_str))
    else:
        puts('No Transactions')


def send_funds(wallet_obj, change_address=None, destination_address=None, dest_satoshis=None, tx_preference=None):
    if not USER_ONLINE:
        puts(colored.red('BlockCypher connection needed to fetch unspents and broadcast signed transaction.'))
        puts(colored.red('You may dump all your addresses and private keys while offline by selecting option 0 on the home screen.'))
        return

    mpub = wallet_obj.serialize_b58(private=False)
    if not wallet_obj.private_key:
        print_pubwallet_notice(mpub=mpub)
        return

    coin_symbol = str(coin_symbol_from_mkey(mpub))
    verbose_print(coin_symbol)

    wallet_name = get_blockcypher_walletname_from_mpub(
            mpub=mpub,
            subchain_indices=[0, 1],
            )
    wallet_details = get_wallet_transactions(
            wallet_name=wallet_name,
            api_key=BLOCKCYPHER_API_KEY,
            coin_symbol=coin_symbol,
            )
    verbose_print(wallet_details)

    if wallet_details['final_balance'] == 0:
        puts(colored.red("0 balance. You can't send funds if you don't have them available!"))
        return

    mpriv = wallet_obj.serialize_b58(private=True)

    if not destination_address:
        display_shortname = COIN_SYMBOL_MAPPINGS[coin_symbol]['display_shortname']
        puts('\nWhat %s address do you want to send to?' % display_shortname)
        puts('Enter "b" to go back.\n')
        destination_address = get_crypto_address(coin_symbol=coin_symbol, quit_ok=True)
        if destination_address is False:
            puts(colored.red('Transaction Not Broadcast!'))
            return

    if not dest_satoshis:

        crypto_units = format_crypto_units(
                input_quantity=wallet_details['final_balance'],
                input_type='satoshi',
                output_type=UNIT_CHOICE,
                coin_symbol=coin_symbol,
                print_cs=True,
                )
        curr_symbol = get_curr_symbol(
                coin_symbol=coin_symbol,
                output_type=UNIT_CHOICE,
                )
        puts('\nHow much (in %s) do you want to send?' % curr_symbol)
        puts('Your current balance is %s.' % crypto_units)
        puts('Note that due to small %s network transaction fees your full balance may not be available to send.' % display_shortname)
        puts('To send your full balance (less transaction fees), enter "-1".')
        puts('Enter "b" to go back.\n')

        dest_crypto_qty = get_crypto_qty(
                max_num=from_satoshis(
                    input_satoshis=wallet_details['final_balance'],
                    output_type=UNIT_CHOICE,
                    ),
                input_type=UNIT_CHOICE,
                user_prompt=DEFAULT_PROMPT,
                quit_ok=True,
                )
        if dest_crypto_qty is False:
            # user aborted with Q
            puts(colored.red('Transaction Not Broadcast!'))
            return

        if dest_crypto_qty == -1:
            dest_satoshis = -1
        else:
            dest_satoshis = to_satoshis(
                    input_quantity=dest_crypto_qty,
                    input_type=UNIT_CHOICE,
                    )

    inputs = [{
            'wallet_name': wallet_name,
            'wallet_token': BLOCKCYPHER_API_KEY,
            }, ]
    outputs = [{
            'value': dest_satoshis,
            'address': destination_address,
            }, ]

    if dest_satoshis == -1:
        sweep_funds = True
        change_address = None
    else:
        sweep_funds = False
        if not change_address:
            change_address = get_unused_change_addresses(
                    wallet_obj=wallet_obj,
                    num_addrs=1,
                    )[0]['pub_address']

    if not tx_preference:
        tx_preference = txn_preference_chooser(user_prompt=DEFAULT_PROMPT)

    verbose_print('Inputs:')
    verbose_print(inputs)
    verbose_print('Outputs:')
    verbose_print(outputs)
    verbose_print('Change Address: %s' % change_address)
    verbose_print('coin symbol: %s' % coin_symbol)
    verbose_print('TX Preference: %s' % tx_preference)

    unsigned_tx = create_unsigned_tx(
        inputs=inputs,
        outputs=outputs,
        change_address=change_address,
        preference=tx_preference,
        coin_symbol=coin_symbol,
        api_key=BLOCKCYPHER_API_KEY,
        # will verify in the next step,
        # that way if there is an error here we can display that to user
        verify_tosigntx=False,
        include_tosigntx=True,
        )

    verbose_print('Unsigned TX:')
    verbose_print(unsigned_tx)

    if 'errors' in unsigned_tx:
        if any([x.get('error', '').startswith('Not enough funds after fees') for x in unsigned_tx['errors']]):
            puts("Sorry, after transaction fees there's not (quite) enough funds to send %s." % (
                format_crypto_units(
                    input_quantity=dest_satoshis,
                    input_type='satoshi',
                    output_type=UNIT_CHOICE,
                    coin_symbol=coin_symbol,
                    print_cs=True,
                )))
            puts('Would you like to send the max you can instead?')
            if confirm(user_prompt=DEFAULT_PROMPT, default=False):
                return send_funds(
                        wallet_obj=wallet_obj,
                        change_address=change_address,
                        destination_address=destination_address,
                        dest_satoshis=-1,  # sweep
                        tx_preference=tx_preference,
                        )
            else:
                puts(colored.red('Transaction Not Broadcast!'))
                return

        else:
            puts(colored.red('TX Error(s): Tx NOT Signed or Broadcast'))
            for error in unsigned_tx['errors']:
                puts(colored.red(error['error']))
            # Abandon
            return

    # Verify TX requested to sign is as expected
    tx_is_correct, err_msg = verify_unsigned_tx(
            unsigned_tx=unsigned_tx,
            outputs=outputs,
            sweep_funds=sweep_funds,
            change_address=change_address,
            coin_symbol=coin_symbol,
            )
    if not tx_is_correct:
        puts(colored.red('TX Error: Tx NOT Signed or Broadcast'))
        puts(colored.red(err_msg))
        # Abandon
        return

    input_addresses = get_input_addresses(unsigned_tx)
    verbose_print('input_addresses')
    verbose_print(input_addresses)

    address_paths = [{'path': x['hd_path'], 'address': x['addresses'][0]} for x in unsigned_tx['tx']['inputs']]

    # be sure all addresses returned
    address_paths_filled = verify_and_fill_address_paths_from_bip32key(
            address_paths=address_paths,
            master_key=mpriv,
            network=guess_network_from_mkey(mpriv),
            )

    verbose_print('adress_paths_filled:')
    verbose_print(address_paths_filled)
    hexkeypair_dict = hexkeypair_list_to_dict(address_paths_filled)

    verbose_print('hexkeypair_dict:')
    verbose_print(hexkeypair_dict)

    if len(hexkeypair_dict.keys()) != len(set(input_addresses)):
        notfound_addrs = set(input_addresses) - set(hexkeypair_dict.keys())
        err_msg = "Couldn't find %s traversing bip32 key" % notfound_addrs
        raise Exception('Traversal Fail: %s' % err_msg)

    privkeyhex_list = [hexkeypair_dict[x]['privkeyhex'] for x in input_addresses]
    pubkeyhex_list = [hexkeypair_dict[x]['pubkeyhex'] for x in input_addresses]

    verbose_print('Private Key List: %s' % privkeyhex_list)
    verbose_print('Public Key List: %s' % pubkeyhex_list)

    # sign locally
    tx_signatures = make_tx_signatures(
            txs_to_sign=unsigned_tx['tosign'],
            privkey_list=privkeyhex_list,
            pubkey_list=pubkeyhex_list,
            )
    verbose_print('TX Signatures: %s' % tx_signatures)

    # final confirmation before broadcast

    if dest_satoshis == -1:
        # remember that sweep TXs cannot verify amounts client-side (only destination addresses)
        dest_satoshis_to_display = unsigned_tx['tx']['total'] - unsigned_tx['tx']['fees']
    else:
        dest_satoshis_to_display = dest_satoshis

    CONF_TEXT = "Send %s to %s with a fee of %s (%s%% of the amount you're sending)?" % (
            format_crypto_units(
                input_quantity=dest_satoshis_to_display,
                input_type='satoshi',
                output_type=UNIT_CHOICE,
                coin_symbol=coin_symbol,
                print_cs=True,
                ),
            destination_address,
            format_crypto_units(
                input_quantity=unsigned_tx['tx']['fees'],
                input_type='satoshi',
                output_type=UNIT_CHOICE,
                coin_symbol=coin_symbol,
                print_cs=True,
                ),
            round(100.0 * unsigned_tx['tx']['fees'] / dest_satoshis_to_display, 4),
            )
    puts(CONF_TEXT)

    if not confirm(user_prompt=DEFAULT_PROMPT, default=True):
        puts(colored.red('Transaction Not Broadcast!'))
        return

    broadcasted_tx = broadcast_signed_transaction(
            unsigned_tx=unsigned_tx,
            signatures=tx_signatures,
            pubkeys=pubkeyhex_list,
            coin_symbol=coin_symbol,
            api_key=BLOCKCYPHER_API_KEY,
    )
    verbose_print('Broadcast TX Details:')
    verbose_print(broadcasted_tx)

    if 'errors' in broadcasted_tx:
        puts(colored.red('TX Error(s): Tx May NOT Have Been Broadcast'))
        for error in broadcasted_tx['errors']:
            puts(colored.red(error['error']))
        return

    tx_hash = broadcasted_tx['tx']['hash']
    tx_url = get_tx_url(
            tx_hash=tx_hash,
            coin_symbol=coin_symbol,
            )
    puts(colored.green('Transaction %s Broadcast' % tx_hash))
    puts(colored.blue(tx_url))

    # Display updated wallet balance info
    display_balance_info(wallet_obj=wallet_obj)


def generate_offline_tx(wallet_obj):
    if not USER_ONLINE:
        puts(colored.red('BlockCypher connection needed to fetch unspents for signing.'))
        return

    # TODO: implement
    puts(colored.red('Feature Coming Soon'))


def sign_tx_offline(wallet_obj):

    if wallet_obj.private_key is None:
        puts(colored.red("bcwallet was booted using a master PUBLIC key %s so it cannot sign transactions.\nPlease load bcwallet with your master PRIVATE key like this:"))
        priv_to_display = '%s123...' % first4mprv_from_mpub(
                mpub=wallet_obj.serialize_b58(private=False))
        print_bcwallet_basic_priv_opening(priv_to_display=priv_to_display)
        puts(BCWALLET_PRIVPIPE_EXPLANATION)
        print_bcwallet_piped_priv_opening(priv_to_display=priv_to_display)
        puts(BCWALLET_PRIVPIPE_CAT_EXPLANATION)
        print_bcwallet_piped_priv_cat_opening()
        puts(BCWALLET_PIPE_ENCRYPTION_EXPLANATION)
        return

    else:
        if USER_ONLINE:
            # double check in case we booted online and then disconnected
            if is_connected_to_blockcypher():
                puts(colored.red("Why are you trying to sign a transaction offline while connected to the internet?"))
                puts(colored.red('This feature is for developers to spend funds on their cold wallet without exposing their private keys to an internet connected machine.'))
                puts(colored.red("If you didn't mean to enter your master PRIVATE key on an internet connected machine, you may want to consider moving your funds to a cold wallet.\n"))

    # TODO: implement
    puts(colored.red('Feature Coming Soon'))


def broadcast_signed_tx(wallet_obj):
    if not USER_ONLINE:
        puts(colored.red('BlockCypher connection needed to broadcast signed transaction.'))
        return

    # TODO: implement
    puts(colored.red('Feature Coming Soon'))


def sweep_funds_from_privkey(wallet_obj):
    if not USER_ONLINE:
        puts(colored.red('BlockCypher connection needed to fetch unspents and broadcast signed transaction.'))
        return

    mpub = wallet_obj.serialize_b58(private=False)
    coin_symbol = str(coin_symbol_from_mkey(mpub))
    network = guess_network_from_mkey(mpub)

    puts('Enter a private key (in WIF format) to send from:')
    puts('Enter "b" to go back.\n')
    wif_obj = get_wif_obj(network=network, user_prompt=DEFAULT_PROMPT, quit_ok=True)

    if wif_obj is False:
        return

    pkey_addr = wif_obj.get_public_key().to_address(compressed=True)

    inputs = [{
            'address': pkey_addr,
            }, ]
    verbose_print('Inputs:\n%s' % inputs)

    dest_addr = get_unused_receiving_addresses(
            wallet_obj=wallet_obj,
            num_addrs=1,
            )[0]['pub_address']

    outputs = [{
            'address': dest_addr,
            'value': -1,  # sweep value
            }, ]
    verbose_print('Outputs:\n%s' % outputs)

    unsigned_tx = create_unsigned_tx(
        inputs=inputs,
        outputs=outputs,
        change_address=None,
        coin_symbol=coin_symbol,
        api_key=BLOCKCYPHER_API_KEY,
        # will verify in the next step,
        # that way if there is an error here we can display that to user
        verify_tosigntx=False,
        include_tosigntx=True,
        )
    verbose_print('Unsigned TX:')
    verbose_print(unsigned_tx)

    if 'errors' in unsigned_tx:
        puts(colored.red('TX Error(s): Tx NOT Signed or Broadcast'))
        for error in unsigned_tx['errors']:
            puts(colored.red(error['error']))
        # Abandon
        return

    # Verify TX requested to sign is as expected
    tx_is_correct, err_msg = verify_unsigned_tx(
            unsigned_tx=unsigned_tx,
            outputs=outputs,
            sweep_funds=True,
            change_address=None,
            coin_symbol=coin_symbol,
            )
    if not tx_is_correct:
        puts(colored.red('TX Error: Tx NOT Signed or Broadcast'))
        puts(colored.red(err_msg))
        # Abandon
        return

    privkeyhex_list, pubkeyhex_list = [], []
    for _ in unsigned_tx['tx']['inputs']:
        privkeyhex_list.append(wif_obj.get_key())
        pubkeyhex_list.append(wif_obj.get_public_key().get_key(
            compressed=True))
    verbose_print('Private Key List: %s' % privkeyhex_list)
    verbose_print('Public Key List: %s' % pubkeyhex_list)

    # sign locally
    tx_signatures = make_tx_signatures(
            txs_to_sign=unsigned_tx['tosign'],
            privkey_list=privkeyhex_list,
            pubkey_list=pubkeyhex_list,
            )
    verbose_print('TX Signatures: %s' % tx_signatures)

    # TODO: add final confirmation before broadcast

    broadcasted_tx = broadcast_signed_transaction(
            unsigned_tx=unsigned_tx,
            signatures=tx_signatures,
            pubkeys=pubkeyhex_list,
            coin_symbol=coin_symbol,
            api_key=BLOCKCYPHER_API_KEY,
    )
    verbose_print('Broadcasted TX')
    verbose_print(broadcasted_tx)

    tx_hash = broadcasted_tx['tx']['hash']
    puts(colored.green('TX Broadcast: %s' % tx_hash))
    tx_url = get_tx_url(
            tx_hash=tx_hash,
            coin_symbol=coin_symbol,
            )
    puts(colored.blue(tx_url))

    # Display updated wallet balance info
    display_balance_info(wallet_obj=wallet_obj)


def print_external_chain():
    puts('\nReceiving Address Chain - m/0/k:')


def print_internal_chain():
    puts('\nChange Address Chain - m/1/k')


def print_key_path_header():
    puts('path (address/wif)')


def print_address_path_header():
    puts('path (address)')


def print_path_info(address, path, coin_symbol, wif=None):

    assert path, path
    assert coin_symbol, coin_symbol
    assert address, address

    if wif:
        address_formatted = '%s/%s' % (address, wif)
    else:
        address_formatted = address

    if USER_ONLINE:
        addr_balance = get_total_balance(
                address=address,
                coin_symbol=coin_symbol,
                )

        with indent(2):
            puts(colored.green('%s (%s) - %s' % (
                path,
                address_formatted,
                format_crypto_units(
                    input_quantity=addr_balance,
                    input_type='satoshi',
                    output_type=UNIT_CHOICE,
                    coin_symbol=coin_symbol,
                    print_cs=True,
                    ),
                )))
    else:
        with indent(2):
            puts(colored.green('%s (%s)' % (
                path,
                address_formatted,
                )))


def dump_all_keys_or_addrs(wallet_obj):
    '''
    Offline-enabled mechanism to dump addresses
    '''

    print_traversal_warning()

    puts('\nDo you understand this warning?')
    if not confirm(user_prompt=DEFAULT_PROMPT, default=False):
        puts(colored.red('Dump Cancelled!'))
        return

    mpub = wallet_obj.serialize_b58(private=False)

    if wallet_obj.private_key:
        desc_str = 'private keys'
    else:
        desc_str = 'addresses'
        puts('Displaying Public Addresses Only')
        puts('For Private Keys, please open bcwallet with your Master Private Key:\n')
        priv_to_display = '%s123...' % first4mprv_from_mpub(mpub=mpub)
        print_bcwallet_basic_priv_opening(priv_to_display=priv_to_display)

    puts('How many %s (on each chain) do you want to dump?' % desc_str)
    puts('Enter "b" to go back.\n')

    num_keys = get_int(
            user_prompt=DEFAULT_PROMPT,
            max_int=10**5,
            default_input='5',
            show_default=True,
            quit_ok=True,
            )

    if num_keys is False:
        return

    if wallet_obj.private_key:
        print_childprivkey_warning()

    puts('-' * 70)
    for chain_int in (0, 1):
        for current in range(0, num_keys):
            path = "m/%d/%d" % (chain_int, current)
            if current == 0:
                if chain_int == 0:
                    print_external_chain()
                    print_key_path_header()
                elif chain_int == 1:
                    print_internal_chain()
                    print_key_path_header()
            child_wallet = wallet_obj.get_child_for_path(path)
            if wallet_obj.private_key:
                wif_to_use = child_wallet.export_to_wif()
            else:
                wif_to_use = None
            print_path_info(
                    address=child_wallet.to_address(),
                    path=path,
                    wif=wif_to_use,
                    coin_symbol=coin_symbol_from_mkey(mpub),
                    )

    puts(colored.blue('\nYou can compare this output to bip32.org'))


def dump_selected_keys_or_addrs(wallet_obj, used=None, zero_balance=None):
    '''
    Works for both public key only or private key access
    '''
    if wallet_obj.private_key:
        content_str = 'private keys'
    else:
        content_str = 'addresses'

    if not USER_ONLINE:
        puts(colored.red('\nInternet connection required, would you like to dump *all* %s instead?' % (
            content_str,
            content_str,
            )))
        if confirm(user_prompt=DEFAULT_PROMPT, default=True):
            dump_all_keys_or_addrs(wallet_obj=wallet_obj)
        else:
            return

    mpub = wallet_obj.serialize_b58(private=False)

    if wallet_obj.private_key is None:
        puts('Displaying Public Addresses Only')
        puts('For Private Keys, please open bcwallet with your Master Private Key:\n')
        priv_to_display = '%s123...' % first4mprv_from_mpub(mpub=mpub)

        print_bcwallet_basic_priv_opening(priv_to_display=priv_to_display)

    chain_address_objs = get_addresses_on_both_chains(
            wallet_obj=wallet_obj,
            used=used,
            zero_balance=zero_balance,
            )

    if wallet_obj.private_key and chain_address_objs:
        print_childprivkey_warning()

    addr_cnt = 0
    for chain_address_obj in chain_address_objs:
        if chain_address_obj['index'] == 0:
            print_external_chain()
        elif chain_address_obj['index'] == 1:
            print_internal_chain()
        print_key_path_header()
        for address_obj in chain_address_obj['chain_addresses']:

            print_path_info(
                    address=address_obj['pub_address'],
                    wif=address_obj.get('wif'),
                    path=address_obj['path'],
                    coin_symbol=coin_symbol_from_mkey(mpub),
                    )

            addr_cnt += 1

    if addr_cnt:
        puts(colored.blue('\nYou can compare this output to bip32.org'))
    else:
        puts('No matching %s in this subset. Would you like to dump *all* %s instead?' % (
            content_str,
            content_str,
            ))
        if confirm(user_prompt=DEFAULT_PROMPT, default=True):
            dump_all_keys_or_addrs(wallet_obj=wallet_obj)


def dump_private_keys_or_addrs_chooser(wallet_obj):
    '''
    Offline-enabled mechanism to dump everything
    '''

    if wallet_obj.private_key:
        puts('Which private keys and addresses do you want?')
    else:
        puts('Which addresses do you want?')
    with indent(2):
        puts(colored.cyan('1: Active - have funds to spend'))
        puts(colored.cyan('2: Spent - no funds to spend (because they have been spent)'))
        puts(colored.cyan('3: Unused - no funds to spend (because the address has never been used)'))
        puts(colored.cyan('0: All (works offline) - regardless of whether they have funds to spend (super advanced users only)'))
        puts(colored.cyan('\nb: Go Back\n'))
    choice = choice_prompt(
            user_prompt=DEFAULT_PROMPT,
            acceptable_responses=[0, 1, 2, 3],
            default_input='1',
            show_default=True,
            quit_ok=True,
            )

    if choice is False:
        return

    if choice == '1':
        return dump_selected_keys_or_addrs(wallet_obj=wallet_obj, zero_balance=False, used=True)
    elif choice == '2':
        return dump_selected_keys_or_addrs(wallet_obj=wallet_obj, zero_balance=True, used=True)
    elif choice == '3':
        return dump_selected_keys_or_addrs(wallet_obj=wallet_obj, zero_balance=None, used=False)
    elif choice == '0':
        return dump_all_keys_or_addrs(wallet_obj=wallet_obj)


def offline_tx_chooser(wallet_obj):
    puts('What do you want to do?:')
    puts(colored.cyan('1: Generate transaction for offline signing'))
    puts(colored.cyan('2: Sign transaction offline'))
    puts(colored.cyan('3: Broadcast transaction previously signed offline'))
    puts(colored.cyan('\nb: Go Back\n'))
    choice = choice_prompt(
            user_prompt=DEFAULT_PROMPT,
            acceptable_responses=range(0, 3+1),
            quit_ok=True,
            default_input='1',
            show_default=True,
            )
    verbose_print('Choice: %s' % choice)

    if choice is False:
        return
    elif choice == '1':
        return generate_offline_tx(wallet_obj=wallet_obj)
    elif choice == '2':
        return sign_tx_offline(wallet_obj=wallet_obj)
    elif choice == '3':
        return broadcast_signed_tx(wallet_obj=wallet_obj)


def send_chooser(wallet_obj):
    puts('What do you want to do?:')
    if not USER_ONLINE:
        puts("(since you are NOT connected to BlockCypher, many choices are disabled)")
    with indent(2):
        puts(colored.cyan('1: Basic send (generate transaction, sign, & broadcast)'))
        puts(colored.cyan('2: Sweep funds into bcwallet from a private key you hold'))
        puts(colored.cyan('3: Offline transaction signing (more here)'))
        puts(colored.cyan('\nb: Go Back\n'))

    choice = choice_prompt(
            user_prompt=DEFAULT_PROMPT,
            acceptable_responses=range(0, 5+1),
            quit_ok=True,
            default_input='1',
            show_default=True,
            )
    verbose_print('Choice: %s' % choice)

    if choice is False:
        return
    elif choice == '1':
        return send_funds(wallet_obj=wallet_obj)
    elif choice == '2':
        return sweep_funds_from_privkey(wallet_obj=wallet_obj)
    elif choice == '3':
        offline_tx_chooser(wallet_obj=wallet_obj)


def wallet_home(wallet_obj):
    '''
    Loaded on bootup (and stays in while loop until quitting)
    '''
    mpub = wallet_obj.serialize_b58(private=False)

    if wallet_obj.private_key is None:
        print_pubwallet_notice(mpub=mpub)
    else:
        print_bcwallet_basic_pub_opening(mpub=mpub)

    coin_symbol = coin_symbol_from_mkey(mpub)
    if USER_ONLINE:
        wallet_name = get_blockcypher_walletname_from_mpub(
                mpub=mpub,
                subchain_indices=[0, 1],
                )

        # Instruct blockcypher to track the wallet by pubkey
        create_hd_wallet(
                wallet_name=wallet_name,
                xpubkey=mpub,
                api_key=BLOCKCYPHER_API_KEY,
                coin_symbol=coin_symbol,
                subchain_indices=[0, 1],  # for internal and change addresses
                )

        # Display balance info
        display_balance_info(wallet_obj=wallet_obj)

    # Go to home screen
    while True:
        wallet_url = get_public_wallet_url(mpub)
        puts('-' * 70 + '\n')

        if coin_symbol in ('bcy', 'btc-testnet'):
            display_shortname = COIN_SYMBOL_MAPPINGS[coin_symbol]['display_shortname']
            if coin_symbol == 'bcy':
                faucet_url = 'https://accounts.blockcypher.com/blockcypher-faucet'
            elif coin_symbol == 'btc-testnet':
                faucet_url = 'https://accounts.blockcypher.com/testnet-faucet'
            puts('Get free %s faucet coins:' % display_shortname)
            puts(colored.blue(faucet_url))
            puts()

            if coin_symbol == 'btc-testnet':
                puts('Please consider returning unused testnet coins to mwmabpJVisvti3WEP5vhFRtn3yqHRD9KNP so we can distribute them to others.\n')

        puts('What do you want to do?:')
        if not USER_ONLINE:
            puts("(since you are NOT connected to BlockCypher, many choices are disabled)")
        with indent(2):
            puts(colored.cyan('1: Show balance and transactions'))
            puts(colored.cyan('2: Show new receiving addresses'))
            puts(colored.cyan('3: Send funds (more options here)'))
            puts(colored.cyan('4: Open wallet url with your browser'))

        with indent(2):
            if wallet_obj.private_key:
                puts(colored.cyan('0: Dump private keys and addresses (advanced users only)'))
            else:
                puts(colored.cyan('0: Dump addresses (advanced users only)'))

            puts(colored.cyan('\nq: Quit bcwallet\n'))

        choice = choice_prompt(
                user_prompt=DEFAULT_PROMPT,
                acceptable_responses=range(0, 4+1),
                quit_ok=True,
                default_input='1',
                )
        verbose_print('Choice: %s' % choice)

        if choice is False:
            puts(colored.green('Thanks for using bcwallet!'))
            print_keys_not_saved()
            break
        elif choice == '1':
            display_recent_txs(wallet_obj=wallet_obj)
        elif choice == '2':
            display_new_receiving_addresses(wallet_obj=wallet_obj)
        elif choice == '3':
            send_chooser(wallet_obj=wallet_obj)
        elif choice == '4':
            webbrowser.open(wallet_url)
        elif choice == '0':
            dump_private_keys_or_addrs_chooser(wallet_obj=wallet_obj)


def cli():

    parser = argparse.ArgumentParser(
            description='''Simple BIP32 HD cryptocurrecy command line wallet, with several unique features. ''' + ' '.join([x[1] for x in EXPLAINER_COPY]))
    parser.add_argument('-w', '--wallet',
            dest='wallet',
            default='',
            help='Master private or public key (starts with xprv and xpub for BTC). Can also be UNIX piped in (-w/--w not needed).',
            )
    parser.add_argument("-v", "--verbose",
            dest='verbose',
            default=False,
            action='store_true',
            help="Show detailed logging info",
            )
    parser.add_argument('-b', '--bc-api-key',
            dest='bc_api_key',
            # For all bcwallet users:
            default='9c339f92713518492a4504c273d1d9f9',
            help='BlockCypher API Key to use. If not supplied the default will be used.',
            )
    parser.add_argument('-u', '--units',
            dest='units',
            default='bit',
            choices=UNIT_CHOICES,
            help='Units to represent the currency in user display.',
            )
    parser.add_argument('--version',
            dest='version',
            default=False,
            action='store_true',
            help="Show version and quit",
            )
    args = parser.parse_args()

    if args.verbose:
        global VERBOSE_MODE
        VERBOSE_MODE = True
    verbose_print('args: %s' % args)

    global UNIT_CHOICE
    UNIT_CHOICE = args.units

    if args.version:
        puts(colored.green(str(pkg_resources.get_distribution("bcwallet"))))
        puts()
        sys.exit()

    if sys.stdin.isatty():
        wallet = args.wallet
        verbose_print('Wallet imported from args')
    else:
        wallet = sys.stdin.readline().strip()
        sys.stdin = open('/dev/tty')
        verbose_print('Wallet imported from pipe')
    verbose_print('wallet %s' % wallet)

    if args.bc_api_key:
        global BLOCKCYPHER_API_KEY
        BLOCKCYPHER_API_KEY = args.bc_api_key
        verbose_print('API Key: %s' % BLOCKCYPHER_API_KEY)
        # Crude check
        if not uses_only_hash_chars(BLOCKCYPHER_API_KEY):
            puts(colored.red('Invalid API Key: %s\n' % BLOCKCYPHER_API_KEY))
            sys.exit()

    puts("\nWelcome to bcwallet!")

    puts("\nHere's what makes bcwallet unique:")
    with indent(2):
        for bullet_point, description in EXPLAINER_COPY:
            puts('-%s: %s' % (bullet_point, description))
    puts()

    if wallet:
        network = guess_network_from_mkey(wallet)
        if network:
            # check if valid mkey
            try:
                wallet_obj = Wallet.deserialize(wallet, network=network)
                mpub = wallet_obj.serialize_b58(private=False)
                if wallet_obj.private_key is None:
                    # input was mpub
                    if mpub != wallet:
                        # safety check
                        puts(colored.red("Invalid entry: %s" % wallet))
            except IndexError:
                puts(colored.red("Invalid entry: %s" % wallet))

            # Run the program:
            return wallet_home(wallet_obj)

        else:
            puts(colored.red("Invalid wallet entry: %s" % wallet))

    else:
        puts("You've opened your HD wallet without specifying a master public or master private key.\n")
        puts("To open your wallet with your master private key:\n")
        print_bcwallet_basic_priv_opening(priv_to_display='xpriv123...\n')
        puts("To open your wallet with your master public key:\n")
        print_bcwallet_basic_priv_opening(priv_to_display='xpub123...\n')

        puts("Let's generate a new master private key (locally) for you to use.\n")
        puts('Which currency do you want to create a wallet for?')
        coin_symbol = coin_symbol_chooser(user_prompt=DEFAULT_PROMPT)
        verbose_print(coin_symbol)

        if not coin_symbol:
            puts('\nQuitting without generating a new wallet!\n')
            sys.exit()

        network = COIN_SYMBOL_TO_BMERCHANT_NETWORK[coin_symbol]

        puts("\nLet's add some extra entropy in case you're on a fresh boot of a virtual machine, or your random number generator has been compromised by an unnamed three letter agency.")
        puts("Please bang on the keyboard for as long as you like and then hit enter.")
        puts("There's no reason to record this value, it cannot be used to recover your keys.")
        extra_entropy = get_user_entropy(user_prompt='฿ (optional)')

        verbose_print(extra_entropy)
        # worst-case assumption (attacker knows keyspace and length)
        entropy_space = len(extra_entropy) ** len(set(extra_entropy))
        bits_entropy = len(bin(entropy_space)) - 2
        verbose_print('bits of extra_entropy: %s' % bits_entropy)

        user_wallet_obj = Wallet.new_random_wallet(network=network,
                user_entropy=extra_entropy)
        mpriv = user_wallet_obj.serialize_b58(private=True)
        mpub = user_wallet_obj.serialize_b58(private=False)

        puts(colored.green('\nYour master PRIVATE key is: %s (guard this CAREFULLY as it can be used to steal your funds)' % mpriv))
        puts(colored.green('Your master PUBLIC key is: %s\n' % mpub))
        puts('bcwallet will now quit. Open your new wallet anytime like this:\n')
        print_bcwallet_basic_priv_opening(priv_to_display=mpriv)
        puts(BCWALLET_PRIVPIPE_EXPLANATION)
        print_bcwallet_piped_priv_opening(priv_to_display=mpriv)
        puts(BCWALLET_PRIVPIPE_CAT_EXPLANATION)
        print_bcwallet_piped_priv_cat_opening()
        puts(BCWALLET_PIPE_ENCRYPTION_EXPLANATION)
        print_keys_not_saved()
        sys.exit()


def invoke_cli():
    if sys.version_info[0] != 2 or sys.version_info[1] != 7:
        puts(colored.red('Sorry, this app must be run with python 2.7'))
        puts(colored.red('Your version: %s' % sys.version))
        if sys.version_info[0] == 3:
            puts(colored.red('Please uninstall bcwallet and reinstall like this:\n'))
            with indent(4):
                puts(colored.magenta('$ pip2 install bcwallet\n'))

        sys.exit()

    # Check if blockcypher is up (basically if the user's machine is online)
    global USER_ONLINE
    if is_connected_to_blockcypher():
        USER_ONLINE = True

        current_bcwallet_version = str(pkg_resources.get_distribution("bcwallet")).split()[1]

        latest_bcwallet_version = None
        try:
            latest_bcwallet_version = get_latest_bcwallet_version()
        except Exception as e:
            puts(colored.red('Unable to lookup latest version number for bcwallet on GitHub'))
            puts(colored.red('The error was:\n'))

            with indent(2):
                puts(colored.yellow(str(e)))

            puts('\nHere are the details to share with the developer for a bug report: \n')
            with indent(2):
                puts(colored.yellow(traceback.format_exc()))

            puts(colored.red('Your bcwallet version: %s' % current_bcwallet_version))
            puts(colored.red('''Please visit the GitHub repository to confirm you're running the latest version:'''))
            puts(colored.blue(GITHUB_URL))

        if latest_bcwallet_version and latest_bcwallet_version != current_bcwallet_version:
            puts(colored.red('WARNING: Your version of bcwallet is out of date!'))
            puts(colored.yellow('You are running %s and the latest version is %s' % (
                current_bcwallet_version,
                latest_bcwallet_version,
                )))
            puts(colored.yellow('For security and usability, you are STRONGLY encouraged to quit and upgrade:\n'))
            with indent(4):
                puts(colored.magenta('$ pip install --upgrade bcwallet \n'))

            puts('Are you sure you want to continue using this old version of bcwallet?')
            if not confirm(user_prompt=DEFAULT_PROMPT, default=False):
                sys.exit()

    try:
        cli()
    except (KeyboardInterrupt, EOFError):
        puts(colored.red('\nQuitting bcwallet...'))
        print_keys_not_saved()
        sys.exit()
    except Exception as e:
        puts(colored.red('\nBad Robot! Quitting on Unexpected Error:\n%s' % e))

        puts('\nHere are the details to share with the developer for a bug report: \n')
        with indent(2):
            puts(colored.yellow(traceback.format_exc()))
        print_keys_not_saved()
        sys.exit()

if __name__ == '__main__':
    '''
    For invocation like this (not tested):
    python bcwallet.py
    '''
    invoke_cli()
