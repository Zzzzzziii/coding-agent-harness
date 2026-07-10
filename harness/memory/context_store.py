from harness.models import Message

class ContextStore:
    def __init__(self, system_prompt: str, max_messages: int = 50):
        self._messages: list[Message] = [Message(role="system", content=system_prompt)]
        self.max_messages = max_messages

    @property
    def messages(self) -> list[Message]:
        return self._messages

    def add(self, msg: Message) -> None:
        self._messages.append(msg)
        self.truncate()

    def truncate(self) -> None:
        if len(self._messages) <= self.max_messages:
            return
        system = self._messages[0]
        rest = self._messages[1:]
        keep = rest[-(self.max_messages - 1):]
        self._messages = [system] + keep