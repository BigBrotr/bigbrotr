import json
import hashlib
import coincurve
import bech32


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
    'e41d2f51b631d627f1c5ed83d66e1535ac0f1542a94db987c93f758c364a7600'

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


def sig_event_id(event_id: str, private_key_hex: str) -> str:
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
    if not isinstance(event_id, str):
        raise TypeError(f"event_id must be a str, not {type(event_id)}")
    if not isinstance(private_key_hex, str):
        raise TypeError(
            f"private_key_hex must be a str, not {type(private_key_hex)}")
    private_key = coincurve.PrivateKey(bytes.fromhex(private_key_hex))
    signature = private_key.sign_schnorr(bytes.fromhex(event_id))
    return signature.hex()


def verify_sig(event_id: str, pubkey: str, sig: str) -> bool:
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
    if not isinstance(event_id, str):
        raise TypeError(f"event_id must be a str, not {type(event_id)}")
    if not isinstance(pubkey, str):
        raise TypeError(f"pubkey must be a str, not {type(pubkey)}")
    if not isinstance(sig, str):
        raise TypeError(f"sig must be a str, not {type(sig)}")
    if len(pubkey) != 64:
        raise ValueError(f"Invalid public key length: {len(pubkey)}")
    if len(sig) != 128:
        raise ValueError(f"Invalid signature length: {len(sig)}")
    pubkey_bytes = bytes.fromhex(pubkey)
    sig_bytes = bytes.fromhex(sig)
    return coincurve.PublicKey(pubkey_bytes).verify_schnorr(sig_bytes, bytes.fromhex(event_id))


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
    sig = sig_event_id(event_id, sec)
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


def to_bech32(prefix: str, hex_str: str) -> str:
    data = bytes.fromhex(hex_str)
    five_bit_data = bech32.convertbits(data, 8, 5, True)
    return bech32.bech32_encode(prefix, five_bit_data)


def to_hex(bech32_str: str) -> str:
    prefix, data = bech32.bech32_decode(bech32_str)
    if prefix is None or data is None:
        raise ValueError("Invalid Bech32 string")
    hex_data = bech32.convertbits(data, 5, 8, False)
    return bytes(hex_data).hex()


def generate_nostr_keypair():
    sk = coincurve.PrivateKey()
    pk = sk.public_key.format(compressed=True)[1:]
    return sk.to_hex(), pk.hex()
