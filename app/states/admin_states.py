"""Generic FSM states for the admin panel.

Rather than one StatesGroup per wizard (which would balloon into dozens of
near-identical states for a panel this large), the admin panel uses a small
number of generic "waiting for X kind of input" states, and stores *what*
is being edited in the FSM context data (`action`, plus whatever ids/keys
are relevant). Every handler that sets one of these states must also call
`state.update_data(action=..., ...)`, and the generic input handler
dispatches on `data["action"]`.
"""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AdminInput(StatesGroup):
    waiting_text = State()
    waiting_image = State()
    waiting_codes_file_or_text = State()
