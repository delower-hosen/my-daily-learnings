from typing import Any


class ChallengeValidator:
    def validate(
        self,
        expected: list[str],
        detected: list[str],
    ) -> dict[str, Any]:
        """
        Strict ordered subsequence match.
        Each expected step must appear in detected, in order.
        Extra steps in detected are allowed (the user may move freely).
        """
        expected = [s.strip().lower() for s in expected if s and s.strip()]
        detected = [s.strip().lower() for s in detected if s and s.strip()]

        if not expected:
            return {"matched": True, "completed": [], "missing": []}

        det_idx = 0
        completed: list[str] = []
        missing: list[str] = []

        for step in expected:
            found = False
            while det_idx < len(detected):
                if detected[det_idx] == step:
                    completed.append(step)
                    det_idx += 1
                    found = True
                    break
                det_idx += 1
            if not found:
                missing.append(step)

        return {
            "matched": len(missing) == 0,
            "completed": completed,
            "missing": missing,
        }
