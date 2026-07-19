"""
MongoDB Storage Layer — Ghostx Community
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Drop-in replacement for the old per-cog JSON file storage. Every cog's
load_x()/save_x() pair now calls db.load(collection)/db.save(collection,
data) instead of reading/writing a .json file — but keeps returning and
accepting the exact same {key: {...}} dict shape, so nothing else in any
cog had to change.

Uses PyMongo (synchronous) on purpose: swapping every load_x()/save_x()
call site across every cog to async/await would be a much bigger, riskier
change for little practical benefit at this bot's scale (it was a
JSON-file bot a moment ago — traffic is not the bottleneck here). Each
call blocks the event loop for roughly a local network round-trip, same
order of magnitude as the file I/O it replaces. If this bot grows into
something high-traffic, swapping this module for Motor (async) later is a
self-contained follow-up — every other file only ever calls db.load()/
db.save(), never touches PyMongo directly.

Connection settings: MONGO_URI / MONGO_DB_NAME in config.py (env vars).
If MONGO_URI isn't set, every call here fails soft (prints a warning,
returns {} / no-ops) instead of crashing the bot — see MONGODB_SETUP.md.
"""

import config

_client = None
_connect_error_shown = False

# In-memory fallback cache — used when MongoDB is not configured.
# Data persists for the lifetime of the bot process (lost on restart).
_memory_cache: dict[str, dict] = {}
_memory_doc_cache: dict[str, dict] = {}


def _get_client():
    global _client
    if _client is None:
        from pymongo import MongoClient
        _client = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=5000)
    return _client


def _get_collection(name: str):
    client = _get_client()
    return client[config.MONGO_DB_NAME][name]


def _warn_once(e: Exception):
    global _connect_error_shown
    if not _connect_error_shown:
        _connect_error_shown = True
        print(f"⚠️ MongoDB unavailable ({e}) — settings won't persist until this is fixed. See MONGODB_SETUP.md.")


def load(collection: str) -> dict:
    """Load a whole collection into {key: value} — same shape the old
    load_x() functions returned from their JSON files."""
    if not config.MONGO_URI:
        # Return a copy of the in-memory cache for this collection
        return {k: dict(v) for k, v in _memory_cache.get(collection, {}).items()}
    try:
        coll = _get_collection(collection)
        result = {}
        for doc in coll.find({}):
            key = str(doc.pop("_id"))
            result[key] = doc
        return result
    except Exception as e:
        _warn_once(e)
        return {k: dict(v) for k, v in _memory_cache.get(collection, {}).items()}


def save(collection: str, data: dict) -> None:
    """Replace a collection's contents with data — same call shape as the
    old save_x(dict) functions."""
    # Always update the in-memory cache so data survives within the session
    _memory_cache[collection] = {k: dict(v) for k, v in data.items()}

    if not config.MONGO_URI:
        return
    try:
        coll = _get_collection(collection)
        new_keys = set(data.keys())
        existing_keys = {str(doc["_id"]) for doc in coll.find({}, {"_id": 1})}

        for key, value in data.items():
            doc = dict(value)
            doc["_id"] = key
            coll.replace_one({"_id": key}, doc, upsert=True)

        removed = existing_keys - new_keys
        if removed:
            coll.delete_many({"_id": {"$in": list(removed)}})
    except Exception as e:
        _warn_once(e)


def load_doc(collection: str, doc_id: str = "singleton") -> dict:
    """Load a single flat document — for cogs that store one settings dict
    rather than the {key: {...}} shape load()/save() use, e.g. panel_settings.py."""
    if not config.MONGO_URI:
        return dict(_memory_doc_cache.get(f"{collection}:{doc_id}", {}))
    try:
        coll = _get_collection(collection)
        doc = coll.find_one({"_id": doc_id})
        if doc:
            doc.pop("_id", None)
            return doc
        return {}
    except Exception as e:
        _warn_once(e)
        return dict(_memory_doc_cache.get(f"{collection}:{doc_id}", {}))


def save_doc(collection: str, data: dict, doc_id: str = "singleton") -> None:
    """Replace a single flat document's contents."""
    _memory_doc_cache[f"{collection}:{doc_id}"] = dict(data)

    if not config.MONGO_URI:
        return
    try:
        coll = _get_collection(collection)
        doc = dict(data)
        doc["_id"] = doc_id
        coll.replace_one({"_id": doc_id}, doc, upsert=True)
    except Exception as e:
        _warn_once(e)
