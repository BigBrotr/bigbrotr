import json
import hashlib
import bech32
import secp256k1

def npub_to_hex(npub: str) -> str:
    if not npub.startswith('npub'): None
    hrp, data = bech32.bech32_decode(npub)
    decoded_bytes = bech32.convertbits(data, 5, 8, False)
    return bytes(decoded_bytes).hex()

def hex_to_npub(hex_str: str) -> str:
    byte_data = bytes.fromhex(hex_str)
    data = bech32.convertbits(byte_data, 8, 5, True)
    npub = bech32.bech32_encode('npub', data)
    return npub

def sign_event_id(event_id: str, private_key_hex: str) -> str:
    private_key = secp256k1.PrivateKey(bytes.fromhex(private_key_hex))
    sig = private_key.schnorr_sign(bytes.fromhex(event_id), bip340tag=None, raw=True)
    return sig.hex()

def calc_event_id(public_key: str, created_at: int, kind_number: int, tags: list, content: str) -> str:
    content = content.replace(r'\n', '\n').replace(r'\"', '\"').replace(r'\\', '\\').replace(r'\r', '\r').replace(r'\t', '\t').replace(r'\b', '\b').replace(r'\f', '\f')
    data = [0, public_key, created_at, kind_number, tags, content]
    data_str = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(data_str.encode('utf-8')).hexdigest()

def verify_signature(event_id: str, pubkey: str, sig: str) -> bool:
    try:
        pub_key = secp256k1.PublicKey(bytes.fromhex("02" + pubkey), True)
        result = pub_key.schnorr_verify(bytes.fromhex(event_id), bytes.fromhex(sig), None, raw=True)
        if result:
            return True
        else:
            return False
    except (ValueError, TypeError) as e:
        return False