import unittest
from unittest.mock import patch

import connector


class ConnectorTests(unittest.TestCase):
    def test_exact_review_and_separate_credentials(self):
        view = {"hold": {"status": "held"}, "review_token": "exact-token"}
        with patch.object(connector, "request_json", side_effect=[view, {"status": "approved"}]) as call:
            result = connector.answer_hold("http://localhost:8181", "approver-key", "hold-1", lambda v: ("approve", "fixture"))
        self.assertEqual(result["status"], "approved")
        self.assertEqual(call.call_args.args[1], "approver-key")
        self.assertEqual(call.call_args.args[2]["review_token"], "exact-token")
        self.assertEqual(call.call_args.args[2]["decision"], "approve")

    def test_model_failure_defers(self):
        def unavailable(view):
            raise OSError("provider unavailable")
        with patch.object(connector, "request_json", side_effect=[{"hold": {"status": "held"}, "review_token": "same"}, {}]) as call:
            connector.answer_hold("http://localhost:8181", "key", "hold-1", unavailable)
        self.assertEqual(call.call_args.args[2]["decision"], "defer")

    def test_trusted_policy_unknown_target_defers(self):
        context = {"policy": {"action": "refund", "target_argument": "order", "amount_parameter": "amount", "max_amount": 100}, "orders": {"known": {"refundable": True, "remaining_amount": 80}}}
        view = {"hold": {"action": "refund", "arguments": {"order": "known"}, "parameters": {"amount": 75}}}
        self.assertEqual(connector.deterministic_policy(view, context)[0], "approve")
        view["hold"]["arguments"]["order"] = "unknown"
        self.assertEqual(connector.deterministic_policy(view, context)[0], "defer")

    def test_defer_is_not_repeated_until_review_changes(self):
        listed = {"holds": [{"hold": {"id": "h", "status": "held"}, "review_token": "r"}]}
        seen = {}
        with patch.object(connector, "request_json", return_value=listed), patch.object(connector, "answer_hold", return_value={"status": "held"}) as answer:
            connector.poll_once("http://localhost", "key", lambda v: ("defer", "fixture"), seen)
            connector.poll_once("http://localhost", "key", lambda v: ("defer", "fixture"), seen)
            self.assertEqual(answer.call_count, 1)
            listed["holds"][0]["review_token"] = "new"
            connector.poll_once("http://localhost", "key", lambda v: ("defer", "fixture"), seen)
            self.assertEqual(answer.call_count, 2)

    def test_systemone_choice_mapping(self):
        with patch.object(connector, "request_json", return_value={"model": "fixture", "answers": {"decision": {"type": "choice", "choice": "reject", "confidence": 0.99}}}) as call:
            decision, model = connector.model_choice({"hold": {"entity_id": "order-1"}}, {"policy": "fixture"}, "http://localhost:8000/v1/systemone")
        self.assertEqual((decision, model), ("reject", "fixture"))
        self.assertEqual(set(call.call_args.args[2]["questions"]["decision"]["criteria"]), connector.CHOICES)

    def test_invalid_model_response_defers(self):
        for response in [None, {"answers": []}, {"answers": {"decision": None}}, {"answers": {"decision": {"type": "choice", "choice": "extend"}}}]:
            with self.subTest(response=response):
                view = {"hold": {"status": "held"}, "review_token": "same"}
                with patch.object(connector, "request_json", side_effect=[view, response, {}]) as call:
                    connector.answer_hold("http://localhost:8181", "key", "hold-1", lambda v: connector.model_choice(v, {}, "http://localhost:8000/v1/systemone"))
                self.assertEqual(call.call_args.args[2]["decision"], "defer")


if __name__ == "__main__":
    unittest.main()
