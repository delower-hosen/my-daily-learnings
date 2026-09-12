import random
from app.core.config import settings


class ChallengeService:
    def generate(self) -> list[str]:
        """
        Generate a random ordered challenge sequence.
        No two consecutive steps are the same direction.
        """
        pool = settings.challenge_pool
        length = settings.challenge_length
        result: list[str] = []

        while len(result) < length:
            candidates = [d for d in pool if not result or d != result[-1]]
            result.append(random.choice(candidates))

        return result


challenge_service = ChallengeService()
