from dataclasses import dataclass


@dataclass
class HostState:
    connected: bool = False
    paused: bool = False
    last_card_type: str = ""
    mode: str = "MEMORY"   # "MEMORY" | "DREAM"

    def is_dream(self) -> bool:
        return self.mode == "DREAM"

    def enter_dream(self) -> None:
        self.mode = "DREAM"

    def exit_dream(self) -> None:
        self.mode = "MEMORY"
