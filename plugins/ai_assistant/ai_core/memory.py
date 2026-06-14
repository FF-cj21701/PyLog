
class MemoryManager:
    def __init__(self, limit=10):
        self.history = []
        self.limit = limit

    def add_user_message(self, content):
        self.history.append(("user", content))
        # We might want to trim history here, but the original code did self.history[-10:] in the worker.
        # I'll keep the full history here and trim when sending.

    def add_ai_message(self, content):
        self.history.append(("assistant", content))

    def add_system_message(self, content):
        # System messages in history? The original code had separate system prompt.
        # But `history` was `list[tuple[str, str]]`.
        self.history.append(("system", content))

    def get_history(self):
        return self.history

    def get_recent_history(self, n=None):
        if n is None:
            n = self.limit
        return self.history[-n:]

    def clear(self):
        self.history = []
    
    def update_limit(self, new_limit):
        """更新历史记录限制"""
        self.limit = new_limit
