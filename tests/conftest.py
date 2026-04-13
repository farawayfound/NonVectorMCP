# -*- coding: utf-8 -*-
"""Pytest configuration — repo root on path for `backend` imports."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
