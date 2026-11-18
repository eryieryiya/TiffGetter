# -*- coding: utf-8 -*-
"""Theme preference persistence.

Schema stored as JSON::

    {"theme_pair": "tokyo-night", "mode": "dark" | "light"}

All public functions MUST NEVER raise exceptions. Errors are silently
swallowed so that GUI startup / shutdown can never be blocked by a
persistence failure.
"""
import json
import os
from typing import Dict


def pref_path() -> str:
    """Return the JSON file path for theme preference storage.

    - Windows: ``%APPDATA%\\TiffGetter\\theme_pref.json``
    - Unix:    ``~/.config/tiffgetter/theme_pref.json``
    """
    if os.name == 'nt':
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
        return os.path.join(base, 'TiffGetter', 'theme_pref.json')
    home = os.environ.get('HOME') or os.path.expanduser('~')
    return os.path.join(home, '.config', 'tiffgetter', 'theme_pref.json')


def load_pref() -> Dict:
    """Load preference dict. Returns ``{}`` on any failure."""
    try:
        path = pref_path()
        if not os.path.exists(path):
            return {}
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:
        return {}


def save_pref(pref: Dict) -> None:
    """Save preference dict. Silently swallows every failure."""
    try:
        if not isinstance(pref, dict):
            return
        path = pref_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + '.tmp'
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(pref, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            if 'path' in dir() and os.path.exists(pref_path() + '.tmp'):
                os.remove(pref_path() + '.tmp')
        except Exception:
            pass
