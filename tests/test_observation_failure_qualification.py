import unittest
from chatgpt_operation.controller.observation_qualification import qualify_failed_probe

def snapshot(probe_state):
    return {
        "schema_version":1,
        "checkpoint":{
            "present":True,"trustworthy":True,"phase_changed":False,
            "rule_revision_changed":False,"scope_changed":False,
            "evidence_contradiction":False,"next_action_known":True,
        },
        "surfaces":[{
            "id":"workflow_run","stability":"MUTABLE","locator_kind":"FLOATING",
            "decision_critical":True,"pin_verified":False,
            "checkpoint_fingerprint":"run:known","current_fingerprint":None,
            "probe_state":probe_state,
            "probe_reads":["actions.runs"],"detail_reads":["actions.jobs"],
            "prewrite_reads":[],
        }],
        "planned_mutations":[],
    }

class ObservationFailureQualificationTests(unittest.TestCase):
    def test_probe_error_is_not_absence_evidence(self):
        q=qualify_failed_probe(snapshot("ERROR"))
        self.assertTrue(q.passed)
        self.assertEqual(q.status,"PROBE_BLOCKED")
        self.assertEqual(q.next_action,"repair_probe_or_hold")
        self.assertFalse(q.absence_claim_allowed)

    def test_missing_observation_requires_probe_not_absence_claim(self):
        result=__import__("chatgpt_operation.controller.state_refresh",fromlist=["evaluate"]).evaluate(snapshot("NOT_RUN"))
        self.assertEqual(result["status"],"PROBE_REQUIRED")
        self.assertEqual(result["next_action"],"execute_probe_reads_then_re_evaluate")

if __name__=="__main__":
    unittest.main()
