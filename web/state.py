"""Shared Streamlit session state, periodic table data, and keyring helpers."""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st
from ase.data import chemical_symbols

from qcai.config import (
    AppSettings,
    load_settings,
    resolve_deepseek_key,
)
from qcai.config import (
    save_deepseek_key as _save_deepseek_key,
)
from qcai.pipeline import JobStore


def get_db_path() -> Path:
    """Resolve SQLite database path from env or session state."""
    raw = os.environ.get("QCAI_DB_PATH") or st.session_state.get(
        "qcai_db_path", "projects/qcai.sqlite"
    )
    return Path(str(raw))


def get_store() -> JobStore:
    """Return JobStore connected to the active SQLite path."""
    return JobStore(get_db_path())


def get_projects_root() -> Path:
    return get_db_path().parent


def load_app_settings() -> AppSettings:
    return load_settings()


def save_deepseek_key(api_key: str) -> None:
    """Store DeepSeek API key in OS keyring; never store in session_state or echo back."""
    _save_deepseek_key(api_key)


def has_deepseek_key(settings: AppSettings | None = None) -> bool:
    """Return True if a DeepSeek API key exists in keyring, env, or settings."""
    return bool(resolve_deepseek_key(settings))


def get_deepseek_key(settings: AppSettings | None = None) -> str:
    """Retrieve DeepSeek API key at runtime (never display in UI)."""
    return resolve_deepseek_key(settings)


# Standard 18-column periodic table layout (rows 1..7, H..Rn coverage)
PERIODIC_ROWS: list[list[str | None]] = [
    ["H", *([None] * 16), "He"],
    ["Li", "Be", *([None] * 10), "B", "C", "N", "O", "F", "Ne"],
    ["Na", "Mg", *([None] * 10), "Al", "Si", "P", "S", "Cl", "Ar"],
    list(chemical_symbols[19:37]),
    list(chemical_symbols[37:55]),
    [
        "Cs",
        "Ba",
        "La",
        *list(chemical_symbols[72:87]),
    ],
]

LANTHANOIDS: list[str] = list(chemical_symbols[58:72])
