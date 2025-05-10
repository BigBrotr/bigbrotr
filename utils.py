import json
import hashlib
import bech32
import secp256k1
import os
import re
import URI_generic_regex as ugr


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
    Sign the event ID using the private key.

    Parameters:
    - event_id (str): The event ID to sign.
    - private_key_hex (str): The private key in hexadecimal format.

    Example:
    >>> sign_event_id('d2c3f4e5b6a7c8d9e0f1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p7q8r9s0t1u2v3', 'private_key_hex')
    'signature'

    Returns:
    - str: The signature of the event ID.

    Raises:
    - TypeError: if event_id or private_key_hex is not a str
    - ValueError: if the private key is invalid
    """
    private_key = secp256k1.PrivateKey(bytes.fromhex(private_key_hex))
    sig = private_key.schnorr_sign(
        bytes.fromhex(event_id), bip340tag=None, raw=True)
    return sig.hex()


def verify_sig(event_id: str, pubkey: str, sig: str) -> bool:
    """
    Verify the signature of an event ID using the public key.

    Parameters:
    - event_id (str): The event ID to verify.
    - pubkey (str): The public key of the user.
    - sig (str): The signature to verify.

    Example:
    >>> verify_signature('d2c3f4e5b6a7c8d9e0f1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p7q8r9s0t1u2v3', 'pubkey', 'signature')
    True

    Returns:
    - bool: True if the signature is valid, False otherwise.

    Raises:
    - TypeError: if event_id, pubkey, or sig is not a str
    - ValueError: if the public key or signature is invalid
    """
    try:
        pub_key = secp256k1.PublicKey(bytes.fromhex("02" + pubkey), True)
        result = pub_key.schnorr_verify(bytes.fromhex(
            event_id), bytes.fromhex(sig), None, raw=True)
        if result:
            return True
        else:
            return False
    except (ValueError, TypeError) as e:
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


def generate_nostr_keypair():
    """
    Generate a Nostr-compatible secp256k1 keypair.
    Returns:
        tuple: (private_key_hex, public_key_hex)
    """
    private_key = os.urandom(32)
    private_key_obj = secp256k1.PrivateKey(private_key)
    public_key = private_key_obj.pubkey.serialize(compressed=True)[1:]
    private_key_hex = private_key.hex()
    public_key_hex = public_key.hex()
    return private_key_hex, public_key_hex


def to_bech32(prefix, hex_str):
    """
    Convert a hex string to Bech32 format.

    Args:
        prefix (str): The prefix for the Bech32 encoding (e.g., 'nsec', 'npub').
        hex_str (str): The hex string to convert.

    Returns:
        str: The Bech32 encoded string.
    """
    byte_data = bytes.fromhex(hex_str)
    data = bech32.convertbits(byte_data, 8, 5, True)
    return bech32.bech32_encode(prefix, data)


def to_hex(bech32_str):
    """
    Convert a Bech32 string to hex format.

    Args:
        bech32_str (str): The Bech32 string to convert.

    Returns:
        str: The hex encoded string.
    """
    prefix, data = bech32.bech32_decode(bech32_str)
    byte_data = bech32.convertbits(data, 5, 8, False)
    return bytes(byte_data).hex()


def find_websoket_relays(text):
    """
    Find all WebSocket relays in the given text.
    Parameters:
    - text (str): The text to search for WebSocket relays.
    Example:
    >>> text = "Connect to wss://relay.example.com:443 and ws://relay.example.com"
    >>> find_websoket_relays(text)
    ['relay.example.com:443', 'relay.example.com']
    Returns:
    - list: A list of WebSocket relay URLs found in the text.
    Raises:
    - TypeError: if text is not a str
    """
    if not isinstance(text, str):
        raise TypeError(f"text must be a str, not {type(text)}")
    result = []
    matches = re.finditer(ugr.URI_GENERIC_REGEX, text, re.VERBOSE)
    for match in matches:
        scheme = match.group("scheme")
        host = match.group("host")
        port = match.group("port")
        port = int(port[1:]) if port else None
        path = match.group("path")
        path = "" if path in ["", "/", None] else "/" + path.strip("/")
        domain = match.group("domain")
        if scheme not in ["ws", "wss"]:
            continue
        if port and (port < 0 or port > 65535):
            continue
        if domain and domain.lower().endswith(".onion") and not re.match(r"^([a-z2-7]{16}|[a-z2-7]{56})\.onion$", domain.lower()):
            continue
        if domain and domain.split(".")[-1].upper() not in ugr.TLDS + ["ONION"]:
            continue
        port = ":" + str(port) if port else ""
        url = host.lower() + port + path
        result.append(url)
    return result
