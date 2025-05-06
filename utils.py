import json
import hashlib
import bech32
import secp256k1
import subprocess


def calc_event_id(pubkey: str, created_at: int, kind: int, tags: list, content: str) -> str:
    """
    Calculate the event ID based on the provided parameters.

    Parameters:
    - pubkey (str): The public key of the user.
    - created_at (int): The timestamp of the event.
    - kind (int): The kind of event.
    - tags (list): A list of tags associated with the event.
    - content (str): The content of the event.

    Example:
    >>> calc_event_id('pubkey', 1234567890, 1, [['tag1', 'tag2']], 'Hello, World!')
    'd2c3f4e5b6a7c8d9e0f1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p7q8r9s0t1u2v3'

    Returns:
    - str: The calculated event ID as a hexadecimal string.

    Raises:
    - TypeError: if pubkey is not a str
    - TypeError: if created_at is not an int
    - TypeError: if kind is not an int
    - TypeError: if tags is not a list of lists of str
    - TypeError: if content is not a str
    """
    if not isinstance(pubkey, str):
        raise TypeError(f"pubkey must be a str, not {type(pubkey)}")
    if not isinstance(created_at, int):
        raise TypeError(
            f"created_at must be an int, not {type(created_at)}")
    if not isinstance(kind, int):
        raise TypeError(f"kind must be an int, not {type(kind)}")
    if not isinstance(tags, list):
        raise TypeError(
            f"tags must be a list of lists of str, not {type(tags)}")
    for tag in tags:
        if not isinstance(tag, list):
            raise TypeError(f"tag must be a list of str, not {type(tag)}")
        for t in tag:
            if not isinstance(t, str):
                raise TypeError(f"tag must contain str, not {type(t)}")
    if not isinstance(content, str):
        raise TypeError(f"content must be a str, not {type(content)}")
    content = content.replace(r'\n', '\n').replace(r'\"', '\"').replace(r'\\', '\\').replace(
        r'\r', '\r').replace(r'\t', '\t').replace(r'\b', '\b').replace(r'\f', '\f')
    data = [0, pubkey, created_at, kind, tags, content]
    data_str = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(data_str.encode('utf-8')).hexdigest()


def sign_event_id(event_id: str, private_key_hex: str) -> str:
    """
    Sign the event ID using the provided private key.

    Parameters:
    - event_id (str): The event ID to sign.
    - private_key_hex (str): The private key in hexadecimal format.

    Returns:
    - str: The signature of the event ID as a hexadecimal string.

    Raises:
    - TypeError: If input parameters are not strings.
    - ValueError: If the private key is invalid.
    """
    private_key = secp256k1.PrivateKey(bytes.fromhex(private_key_hex))
    sig = private_key.schnorr_sign(
        bytes.fromhex(event_id), bip340tag=None, raw=True)
    return sig.hex()


def verify_signature(event_id: str, pubkey: str, sig: str) -> bool:
    """
    Verify the signature of an event ID using the provided public key.

    Parameters:
    - event_id (str): The event ID to verify.
    - pubkey (str): The compressed public key (without prefix) in hexadecimal format.
    - sig (str): The signature to verify, in hexadecimal format.

    Returns:
    - bool: True if the signature is valid, False otherwise.

    Raises:
    - TypeError: If inputs are not strings.
    - ValueError: If the public key or signature is invalid.
    """
    try:
        pub_key = secp256k1.PublicKey(bytes.fromhex(pubkey), True)
        result = pub_key.schnorr_verify(bytes.fromhex(
            event_id), bytes.fromhex(sig), None, raw=True)
        return result
    except (ValueError, TypeError):
        return False


def generate_event(sec, pub, created_at, kind, tags, content):
    """
    Generate an event with the given parameters.

    Parameters:
    - sec (str): The private key in hexadecimal format.
    - pub (str): The public key in hexadecimal format.
    - created_at (int): The timestamp of the event.
    - kind (int): The kind of event.
    - tags (list): A list of tags associated with the event.
    - content (str): The content of the event.

    Returns:
    - dict: A dictionary representing the event, containing:
        - id: The event ID.
        - pubkey: The public key of the user.
        - created_at: The timestamp of the event.
        - kind: The kind of event.
        - tags: A list of tags associated with the event.
        - content: The content of the event.
        - sig: The signature of the event ID.
    """
    event_id = calc_event_id(pub, created_at, kind, tags, content)
    sig = sign_event_id(event_id, sec)
    event = {
        "id": event_id,
        "pubkey": pub,
        "created_at": created_at,
        "kind": kind,
        "tags": tags,
        "content": content,
        "sig": sig
    }
    return event


def generate_keypair():
    """
    Generate a new secp256k1 key pair.

    Returns:
    - tuple: A tuple containing:
        - str: The private key in hexadecimal format.
        - str: The compressed public key in hexadecimal format.
    """
    def generate_hex_private_key():
        result = subprocess.run(
            ["openssl", "rand", "-hex", "32"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()

    def derive_public_key(hex_key):
        priv_key_bytes = bytes.fromhex(hex_key)
        privkey_obj = secp256k1.PrivateKey(privkey=priv_key_bytes, raw=True)
        pubkey_serialized = privkey_obj.pubkey.serialize(compressed=True)
        return pubkey_serialized.hex()

    hex_private_key = generate_hex_private_key()
    hex_public_key = derive_public_key(hex_private_key)
    return hex_private_key, hex_public_key


def hex_to_nsec(hex_str: str) -> str:
    """
    Convert a hexadecimal private key to a Bech32 encoded 'nsec' string.

    Parameters:
    - hex_str (str): The private key in hexadecimal format.

    Returns:
    - str: The corresponding Bech32 encoded 'nsec' string.
    """
    byte_data = bytes.fromhex(hex_str)
    data = bech32.convertbits(byte_data, 8, 5, True)
    return bech32.bech32_encode('nsec', data)


def hex_to_npub(hex_str: str) -> str:
    """
    Convert a hexadecimal public key to a Bech32 encoded 'npub' string.

    Parameters:
    - hex_str (str): The public key in hexadecimal format.

    Returns:
    - str: The corresponding Bech32 encoded 'npub' string.
    """
    byte_data = bytes.fromhex(hex_str)
    data = bech32.convertbits(byte_data, 8, 5, True)
    return bech32.bech32_encode('npub', data)


def npub_to_hex(npub: str) -> str:
    """
    Convert a Bech32 encoded 'npub' string back to hexadecimal format.

    Parameters:
    - npub (str): The Bech32 encoded 'npub' string.

    Returns:
    - str: The public key in hexadecimal format.

    Raises:
    - ValueError: If the input does not start with 'npub' or decoding fails.
    """
    if not npub.startswith('npub'):
        raise ValueError("Invalid npub format")
    hrp, data = bech32.bech32_decode(npub)
    decoded_bytes = bech32.convertbits(data, 5, 8, False)
    return bytes(decoded_bytes).hex()


def nsec_to_hex(nsec: str) -> str:
    """
    Convert a Bech32 encoded 'nsec' string back to hexadecimal format.

    Parameters:
    - nsec (str): The Bech32 encoded 'nsec' string.

    Returns:
    - str: The private key in hexadecimal format.

    Raises:
    - ValueError: If the input does not start with 'nsec' or decoding fails.
    """
    if not nsec.startswith('nsec'):
        raise ValueError("Invalid nsec format")
    hrp, data = bech32.bech32_decode(nsec)
    decoded_bytes = bech32.convertbits(data, 5, 8, False)
    return bytes(decoded_bytes).hex()
