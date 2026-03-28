from typing import List, Dict, Any


class ChallengeValidationService:
    def validate_sequence(self, expected_steps: List[str], detected_steps: List[str]) -> Dict[str, Any]:
        expected = [step.strip().lower() for step in expected_steps if step and step.strip()]
        detected = [step.strip().lower() for step in detected_steps if step and step.strip()]

        if not expected:
            return {
                "matched": True,
                "completed_steps": detected,
                "missing_steps": [],
                "wrong_order": False
            }

        # strict ordered subsequence match
        detected_index = 0
        completed: List[str] = []
        missing: List[str] = []

        for expected_step in expected:
            found = False
            while detected_index < len(detected):
                if detected[detected_index] == expected_step:
                    completed.append(expected_step)
                    detected_index += 1
                    found = True
                    break
                detected_index += 1

            if not found:
                missing.append(expected_step)

        matched = len(missing) == 0

        return {
            "matched": matched,
            "completed_steps": completed,
            "missing_steps": missing,
            "wrong_order": not matched
        }