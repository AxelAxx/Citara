"""Citara session state: the keys contract, state callbacks, and the enum crossing.

Extracted from app.py as V2 step 2 (presentation refactor). Two contracts live here
on purpose:

- The ``KEY_*`` constants name every ``st.session_state`` slot the app uses. main()
  and the callbacks share these constants, never raw strings, so a typo becomes a
  loud ``NameError`` instead of a silently fresh state slot.
- ``config_for`` is the ONE place presentation crosses the closed ``Vertical`` enum
  (BYOD lens): everywhere else the active collection is an opaque ``str`` id. In V3
  this body swaps to a dynamic collection registry and no caller changes.
"""

from __future__ import annotations

import streamlit as st

from core.ingest import load_vertical_config
from core.models import Vertical, VerticalConfig

# --- session-state keys (the contract) ----------------------------------------
# KEY_VERTICAL is the ONE source of truth for the active collection id. The sidebar
# selectbox deliberately has its OWN widget key (KEY_VERTICAL_WIDGET) and syncs back
# via sync_vertical — binding the widget directly to KEY_VERTICAL desyncs on the
# widget's first mount (see the comment at the selectbox in main).
KEY_VERTICAL = "vertical"
KEY_VERTICAL_WIDGET = "vertical_widget"
KEY_ENTERED = "entered"
KEY_PENDING_QUERY = "pending_query"
KEY_HISTORIES = "histories"
KEY_HAS_GENERATED = "has_generated"


def config_for(collection_id: str) -> VerticalConfig:
    """Resolve a collection id to its VerticalConfig — the ONE enum crossing.

    BYOD lens: presentation treats the active collection as an opaque ``str``;
    only this helper meets the closed ``Vertical`` enum on the way into core's
    config loader. When V3 replaces the enum with runtime-created Collections,
    this body changes and every call site stays put.
    """
    return load_vertical_config(Vertical(collection_id))


def history_for(vertical_value: str) -> list[dict]:
    """The chat history for a Vertical, isolated from the others.

    Keyed by Vertical so switching legal↔health does not mix two distinct
    conversations (and their sources) into one thread.
    """
    histories = st.session_state.setdefault(KEY_HISTORIES, {})
    return histories.setdefault(vertical_value, [])


def queue_query(question: str) -> None:
    """on_click of an example-question button: queue it for the next rerun.

    The queued value is consumed at the top of main's render cycle and fed
    through the exact same path as a typed ``st.chat_input`` prompt — one
    handler for both entry points, no duplicated query flow.
    """
    st.session_state[KEY_PENDING_QUERY] = question


def select_vertical(vertical_value: str) -> None:
    """on_click of a welcome domain card: select the Vertical, stay on the welcome.

    Writes the flat KEY_VERTICAL state — the ONE source of truth for the active
    Vertical, which the sidebar switcher seeds from and syncs back to (see
    sync_vertical). Selecting is deliberately NOT entering — that is
    "Comenzar"'s job (enter_chat).
    """
    st.session_state[KEY_VERTICAL] = vertical_value


def sync_vertical() -> None:
    """on_change of the sidebar switcher: copy the widget value to KEY_VERTICAL.

    The widget key and the flat key are deliberately separate — binding the
    widget directly to KEY_VERTICAL desyncs on first mount (see the comment at
    the selectbox in main).
    """
    st.session_state[KEY_VERTICAL] = st.session_state[KEY_VERTICAL_WIDGET]


def enter_chat() -> None:
    """on_click of the welcome's "Comenzar" button: enter the chat.

    ``entered`` stays True for the rest of the session — switching Verticals
    mid-session must never route back through the welcome.
    """
    st.session_state[KEY_ENTERED] = True
