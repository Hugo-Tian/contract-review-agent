"""Region selection. REGION=cn|hk; this branch defaults to hk.

Resolved on every call so one process (and the tests) can switch region via the
environment; an unknown value is a configuration error, never a silent fallback.
"""
import os
from .base import Profile
from . import cn, hk

PROFILES = {'cn': cn.PROFILE, 'hk': hk.PROFILE}
DEFAULT_REGION = 'hk'


def current() -> Profile:
    region = os.getenv('REGION', DEFAULT_REGION).strip().lower() or DEFAULT_REGION
    if region not in PROFILES:
        raise RuntimeError(f'未知 REGION={region!r}，只支持 cn 或 hk。')
    return PROFILES[region]
