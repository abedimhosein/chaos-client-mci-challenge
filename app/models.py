from dataclasses import dataclass


@dataclass
class Node:
    base_url: str

    def __post_init__(self) -> None:
        self.base_url = self.base_url.strip().rstrip("/")

        if not self.base_url:
            raise ValueError("Node base-url cannot be empty")


@dataclass
class Group:
    group_id: str

    def __post_init__(self) -> None:
        self.group_id = self.group_id.strip()

        if not self.group_id:
            raise ValueError("group-id cannot be empty")
