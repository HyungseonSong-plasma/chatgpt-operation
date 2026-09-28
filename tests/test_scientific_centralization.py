import copy
import unittest

from chatgpt_operation.controller.centralization import (
    CentralizationManifestError,
    retirement_candidates,
    validate_manifest,
)


def manifest():
    return {
        "schema_version":1,
        "canonical_repository":"HyungseonSong-plasma/chatgpt-operation",
        "retirement_policy":{
            "require_exact_canonical_revision":True,
            "require_compatibility_verification":True,
            "require_consumer_ci_success":True,
            "require_no_remaining_local_imports":True,
            "delete_only_through_consumer_policy":True,
        },
        "components":[{
            "id":"semantic-ir",
            "origin_repository":"HyungseonSong-plasma/moose-test-repo",
            "origin_revision":"a"*40,
            "origin_paths":["physics_harness/ontology/records.py"],
            "canonical_paths":["src/chatgpt_operation/science/ontology.py"],
            "phase":"centralized",
            "consumers":[{
                "repository":"HyungseonSong-plasma/moose-test-repo",
                "duplicate_paths":["physics_harness/ontology/records.py"],
                "status":"pending_cutover",
                "canonical_revision":None,
                "verification":{
                    "compatibility_verified":False,
                    "consumer_ci_success":False,
                    "remaining_local_imports":1,
                },
            }],
        }],
    }


class CentralizationContractTests(unittest.TestCase):
    def test_centralized_component_is_not_yet_a_retirement_candidate(self):
        raw=validate_manifest(manifest())
        self.assertEqual(
            retirement_candidates(
                raw,
                repository="HyungseonSong-plasma/moose-test-repo",
            ),
            (),
        )

    def test_retirement_requires_explicit_verified_cutover_and_ready_phase(self):
        raw=manifest()
        item=raw["components"][0]
        item["phase"]="retirement_ready"
        consumer=item["consumers"][0]
        consumer["status"]="cutover_verified"
        consumer["canonical_revision"]="b"*40
        consumer["verification"]={
            "compatibility_verified":True,
            "consumer_ci_success":True,
            "remaining_local_imports":0,
        }
        candidate=retirement_candidates(
            raw,
            repository="HyungseonSong-plasma/moose-test-repo",
        )
        self.assertEqual(len(candidate),1)
        self.assertEqual(candidate[0].component_id,"semantic-ir")
        self.assertEqual(
            candidate[0].duplicate_paths,
            ("physics_harness/ontology/records.py",),
        )

    def test_verified_cutover_without_exact_revision_fails_closed(self):
        raw=manifest()
        consumer=raw["components"][0]["consumers"][0]
        consumer["status"]="cutover_verified"
        consumer["verification"]={
            "compatibility_verified":True,
            "consumer_ci_success":True,
            "remaining_local_imports":0,
        }
        with self.assertRaisesRegex(
            CentralizationManifestError,
            "canonical_revision",
        ):
            validate_manifest(raw)

    def test_retirement_policy_cannot_silently_disable_a_safety_gate(self):
        raw=copy.deepcopy(manifest())
        raw["retirement_policy"]["require_consumer_ci_success"]=False
        with self.assertRaisesRegex(
            CentralizationManifestError,
            "safety gates",
        ):
            validate_manifest(raw)


if __name__=="__main__":
    unittest.main()
