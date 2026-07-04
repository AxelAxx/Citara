"""Citara session state: the keys contract, state callbacks, and the enum crossing.

Extracted from app.py as V2 step 2 (presentation refactor). Two contracts live here
on purpose:

- The ``KEY_*`` constants name every ``st.session_state`` slot the app uses. main()
  and the callbacks share these constants, never raw strings, so a typo becomes a
  loud ``NameError`` instead of a silently fresh state slot.
- ``config_for`` and ``vertical_options`` are the ONLY places presentation crosses
  the closed ``Vertical`` enum (BYOD lens): everywhere else the active collection is
  an opaque ``str`` id. In V3 these bodies swap to a dynamic collection registry and
  no caller changes.
"""

from __future__ import annotations

import streamlit as st

from core.ingest import load_vertical_config
from core.models import RagEngineError, Vertical, VerticalConfig

# --- session-state keys (the contract) ----------------------------------------
# KEY_VERTICAL is the ONE source of truth for the active collection id. Both
# switchers (welcome cards and sidebar cards) are buttons whose on_click
# (select_vertical) writes it directly — buttons hold no value, so there is no
# widget key and no sync callback.
KEY_VERTICAL = "vertical"
KEY_ENTERED = "entered"
KEY_PENDING_QUERY = "pending_query"
KEY_HISTORIES = "histories"
KEY_HAS_GENERATED = "has_generated"
# Set by the sidebar's "Gestionar corpus" trigger; consumed (one-shot) by
# render_corpus_dialog, which opens the corpus st.dialog.
KEY_CORPUS_OPEN = "corpus_open"


def config_for(collection_id: str) -> VerticalConfig:
    """Resolve a collection id to its VerticalConfig — the ONE enum crossing.

    BYOD lens: presentation treats the active collection as an opaque ``str``;
    only this helper meets the closed ``Vertical`` enum on the way into core's
    config loader. When V3 replaces the enum with runtime-created Collections,
    this body changes and every call site stays put.
    """
    return load_vertical_config(Vertical(collection_id))


@st.cache_data(show_spinner=False)
def vertical_options() -> list[tuple[str, str]]:
    """The selectable Verticals as (value, display_name), skipping any unconfigured.

    Cached as data because it is just a cheap read of small YAML files; building the
    option list once per session is enough.
    """
    # BYOD seam: the ONE place that decides WHICH collections exist. Today the
    # available collections are exactly the configured Vertical enum values; in
    # V3 this line will list the user's runtime-created Collections instead.
    # Everything downstream (cards, switcher, routing) iterates the returned
    # options and hardcodes neither the count nor the ids.
    available_collection_ids = [vertical.value for vertical in Vertical]

    options: list[tuple[str, str]] = []
    for collection_id in available_collection_ids:
        try:
            config = config_for(collection_id)
        except RagEngineError:
            continue  # a collection with no/invalid YAML simply isn't offered
        options.append((collection_id, config.display_name))
    return options


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
    """on_click of a domain card (welcome or sidebar): select the Vertical.

    Writes the flat KEY_VERTICAL state — the ONE source of truth for the active
    Vertical. On the welcome, selecting is deliberately NOT entering — that is
    "Comenzar"'s job (enter_chat).
    """
    st.session_state[KEY_VERTICAL] = vertical_value


def enter_chat() -> None:
    """on_click of the welcome's "Comenzar" button: enter the chat.

    ``entered`` stays True for the rest of the session — switching Verticals
    mid-session must never route back through the welcome.
    """
    st.session_state[KEY_ENTERED] = True
