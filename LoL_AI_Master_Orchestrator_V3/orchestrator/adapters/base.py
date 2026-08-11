from abc import ABC, abstractmethod

class AgentAdapter(ABC):
    @abstractmethod
    def doctor(self): ...
    @abstractmethod
    def run(self, request): ...
