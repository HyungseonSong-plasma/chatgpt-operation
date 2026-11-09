"""Native Child Issue POST/PATCH/link/recovery with fake exact GitHub REST."""
from __future__ import annotations

import copy
import hashlib
import unittest
from concurrent.futures import ThreadPoolExecutor

from chatgpt_operation.controller.agent_issue_partition import (
    child_issue_body, validate_child_ownership,
)
from chatgpt_operation.controller.agent_issue_provision import (
    ProvisionError, create_provision, plan_next_child_provision,
)

REPO = "HyungseonSong-plasma/chatgpt-operation"
AUTHOR = "github-actions[bot]"
ROOT = "https://api.github.com/repos/" + REPO + "/issues/"


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def spec(i):
    return create_provision(
        repository=REPO, parent_issue=400, agent_id=f"agent-{i:03}",
        work_id="issue:400", plan_sha256=sha("approved plan"),
        policy_sha256=sha("approved policy"), source_head_sha="a"*40,
        units=[{"id":"scan-0", "input_sha256":sha(f"unit-{i}"),
                "requires":[], "gates":["evidence"]}],
    )


class LiveGithub:
    def __init__(self):
        self.issues = {
            400: {"number":400,"id":4400,"url":ROOT+"400","state":"open",
                 "body":"Original canonical parent — unchanged", "labels":["samuel"]},
        }
        self.comments = {
            400: [{"id":88,"body":"<!-- samuel-controller-state --> original",
                  "created_at":"2026-11-09T00:00:00Z",
                  "updated_at":"2026-11-09T00:00:00Z",
                  "user":{"login":AUTHOR}}],
        }
        self.links = {400:[]}
        self.events = []
        self.next_issue = 500
        self.next_comment = 100
        self.lose_ack = set()

    def get(self,path,*,query=None):
        self.events.append(("GET",path))
        if path == "/issues":
            if query is None or query.get("state")!="all":
                raise AssertionError("Issue inventory must enumerate open and closed")
            items=list(self.issues.values())
        elif path.startswith("/issues/") and path.endswith("/sub_issues"):
            n=int(path.split("/")[2])
            items=[self.issues[x] for x in self.links.get(n, [])]
        elif path.startswith("/issues/") and path.endswith("/comments"):
            n=int(path.split("/")[2])
            items=self.comments.get(n,[])
        elif path.startswith("/issues/") and path.count("/")==2:
            return copy.deepcopy(self.issues[int(path.rsplit("/",1)[-1])])
        else:
            raise AssertionError("unapproved GET "+path)
        if query is None:
            raise AssertionError("unbounded GitHub list read")
        page=int(query["page"])
        return copy.deepcopy(items[(page-1)*100:page*100])

    def request(self,method,path,*,payload=None):
        self.events.append((method,path))
        if method=="POST" and path=="/issues":
            n=self.next_issue
            self.next_issue+=1
            self.issues[n]={
                "number":n, "id":10000+n,
                "url":ROOT+str(n), "state":"open",
                "body":payload["body"], "labels":payload["labels"],
            }
            self.comments[n]=[]
            status=201
            result=self.issues[n]
        elif method=="PATCH" and path.startswith("/issues/"):
            n=int(path.split("/")[-1])
            self.issues[n]["body"]=payload["body"]
            status=200
            result=self.issues[n]
        elif method=="POST" and path=="/issues/400/sub_issues":
            target=next(
                n for n,item in self.issues.items()
                if item["id"]==payload["sub_issue_id"]
            )
            if target not in self.links[400]:
                self.links[400].append(target)
            status=201
            result=self.issues[target]
        elif method=="POST" and path=="/issues/400/comments":
            self.next_comment+=1
            result={
                "id":self.next_comment, "body":payload["body"],
                "user":{"login":AUTHOR},
                "created_at":"2026-11-09T00:00:00Z",
                "updated_at":"2026-11-09T00:00:00Z",
            }
            self.comments[400].append(result)
            status=201
        else:
            raise AssertionError("unapproved REST mutation "+method+" "+path)
        if method+path in self.lose_ack:
            self.lose_ack.remove(method+path)
            raise TimeoutError("operation committed but API ACK lost")
        return status,copy.deepcopy(result)


def next_step(github,request):
    return plan_next_child_provision(
        github,request,parent_issue=copy.deepcopy(github.issues[44]),
        trusted_author=AUTHOR,
    )


def complete(github,request,*,fail_at=None):
    steps=[]
    for _ in range(8):
        step=next_step(github,request)
        steps.append(step["status"])
        if step["status"]=="READY":
            return steps,step["assignment"]
        if fail_at==step["status"]:
            raise RuntimeError("simulated bootstrap SIGKILL just before "+fail_at)
        github.request(step["method"],step["path"],payload=step["payload"])
    raise AssertionError("provisioning did not converge")


class AgentProvisioningTests(unittest.TestCase):
    def test_one_agent_provisions_child_and_native_subissue_once(self):
        gh=LiveGithub()
        stages,assignment=complete(gh,spec(1))
        self.assertEqual(stages,[
            "CREATE_CHILD","FINALIZE_CHILD","LINK_CHILD",
            "RECORD_PARENT_ASSIGNMENT","READY",
        ])
        self.assertEqual(assignment["child_issue"],500)
        self.assertEqual(gh.links[44],[500])
        self.assertEqual(len(gh.comments[44]),2)
        self.assertEqual(gh.issues[44]["body"],"Original canonical parent — unchanged")
        self.assertEqual(complete(gh,spec(1))[0],["READY"])
        self.assertEqual(len([e for e in gh.events if e==("POST","/issues")]),1)
        validate_child_ownership(
            gh.issues[500],assignment,parent_registry=[assignment],
        )

    def test_twenty_parallel_requests_are_serially_allocated_by_parent(self):
        gh=LiveGithub()
        with ThreadPoolExecutor(max_workers=10) as pool:
            desired=list(pool.map(spec,range(20)))
        registered=[]
        for item in desired:
            steps,assn=complete(gh,item)
            registered.append(assn)
            self.assertEqual(steps[-1],"READY")
        self.assertEqual(len({x["child_issue"] for x in registered}),20)
        self.assertEqual(len({x["agent_id"] for x in registered}),20)
        self.assertEqual(len(gh.links[44]),20)
        self.assertEqual(len(gh.comments[44]),21)  # state + 20 immutable allocations
        self.assertFalse(any(e==("PATCH","/issues/400") for e in gh.events))
        self.assertEqual(
            len([e for e in gh.events if e==("POST","/issues")]),20,
        )
        for item in desired:
            self.assertEqual(next_step(gh,item)["status"],"READY")
        print("AGENT_CHILD_PROVISION=PASS created=20 linked=20 "
              "replayed=20 duplicates=0 parent_state_patch=0",flush=True)

    def test_lost_ack_after_issue_creation_does_not_create_second_child(self):
        gh=LiveGithub()
        gh.lose_ack.add("POST/issues")
        with self.assertRaisesRegex(TimeoutError,"ACK lost"):
            complete(gh,spec(0))
        steps,assignment=complete(gh,spec(0))
        self.assertNotIn("CREATE_CHILD",steps)
        self.assertEqual(assignment["child_issue"],500)
        self.assertEqual(len(gh.links[44]),1)
        self.assertEqual(len([x for x in gh.events if x==("POST","/issues")]),1)

    def test_lost_ack_at_each_intermediate_boundary_is_recoverable(self):
        for method,path in (
            ("PATCH","/issues/500"),
            ("POST","/issues/400/sub_issues"),
            ("POST","/issues/400/comments"),
        ):
            with self.subTest(method=method,path=path):
                gh=LiveGithub()
                gh.lose_ack.add(method+path)
                with self.assertRaises(TimeoutError):
                    complete(gh,spec(0))
                stages,assignment=complete(gh,spec(0))
                self.assertEqual(stages[-1],"READY")
                self.assertEqual(len(gh.comments[44]),2)
                self.assertEqual(len(gh.links[44]),1)
                self.assertEqual(assignment["child_issue"],500)

    def test_bootstrap_restart_before_each_stage_resumes_only_that_stage(self):
        for blocked in (
            "CREATE_CHILD", "FINALIZE_CHILD", "LINK_CHILD",
            "RECORD_PARENT_ASSIGNMENT",
        ):
            with self.subTest(stage=blocked):
                gh=LiveGithub()
                with self.assertRaisesRegex(RuntimeError,"SIGKILL"):
                    complete(gh,spec(0),fail_at=blocked)
                steps,_=complete(gh,spec(0))
                self.assertEqual(steps[0],blocked)
                self.assertEqual(steps[-1],"READY")
                self.assertEqual(len(gh.comments[44]),2)

    def test_duplicate_provision_intent_in_two_issues_fails_closed(self):
        gh=LiveGithub()
        gh.request("POST","/issues",payload={
            "body":__import__(
                "chatgpt_operation.controller.agent_issue_provision",
                fromlist=["initial_child_body"],
            ).initial_child_body(spec(0)),"labels":[],
        })
        gh.request("POST","/issues",payload={
            "body":__import__(
                "chatgpt_operation.controller.agent_issue_provision",
                fromlist=["initial_child_body"],
            ).initial_child_body(spec(0)),"labels":[],
        })
        with self.assertRaisesRegex(ProvisionError,"duplicate provisional"):
            next_step(gh,spec(0))

    def test_parent_identity_and_child_admission_tampering_are_blocked(self):
        gh=LiveGithub()
        parent=copy.deepcopy(gh.issues[44])
        parent["number"]=999
        with self.assertRaisesRegex(ProvisionError,"parent live Issue"):
            plan_next_child_provision(gh,spec(0),parent_issue=parent)
        complete(gh,spec(0))
        gh.issues[500]["labels"]=[{"name":"samuel"}]
        with self.assertRaisesRegex(ProvisionError,"mistakenly admitted"):
            next_step(gh,spec(0))

    def test_parent_authority_comment_is_immutable_append_not_state_patch(self):
        gh=LiveGithub()
        complete(gh,spec(0))
        state_before=gh.comments[44][0]["body"]
        self.assertEqual(state_before,"<!-- samuel-controller-state --> original")
        self.assertNotIn(("PATCH","/issues/400/comments/88"),gh.events)
        gh.comments[44][1]["updated_at"]="2026-11-09T00:00:01Z"
        with self.assertRaisesRegex(ProvisionError,"not immutable"):
            next_step(gh,spec(0))

    def test_a_conflicting_assignment_for_same_agent_blocks(self):
        gh=LiveGithub()
        complete(gh,spec(0))
        mutated=spec(0)
        mutated["units"][0]["input_sha256"]=sha("different")
        # A changed immutable intent is a *different* plan and cannot be
        # silently taken as a previous assignment.
        from chatgpt_operation.controller.agent_issue_provision import create_provision
        changed=create_provision(
            repository=REPO,parent_issue=400,agent_id="agent-000",
            work_id="issue:400",plan_sha256=sha("approved plan"),
            policy_sha256=sha("approved policy"),source_head_sha="a"*40,
            units=[{"id":"scan-0","input_sha256":sha("different"),
                    "requires":[],"gates":["evidence"]}],
        )
        # The planner must prevent creating another Child for an agent
        # already registered in the same parent work scope.
        with self.assertRaisesRegex(ProvisionError,"parent agent allocation conflict"):
            next_step(gh,changed)


if __name__=="__main__":
    unittest.main()
