from __future__ import annotations


class IdFactory:
    def __init__(self) -> None:
        self._event_counter = 0
        self._signal_counter = 0

    def next_event_id(self) -> str:
        self._event_counter += 1
        return f"evt_{self._event_counter:06d}"

    def next_signal_instance_id(self) -> str:
        self._signal_counter += 1
        return f"sig_{self._signal_counter:06d}"
