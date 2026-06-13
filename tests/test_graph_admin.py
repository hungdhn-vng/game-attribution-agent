from gaa.graph import GraphAgent


class StubAdmin:
    def __init__(self):
        self.calls = []

    def handle(self, action, payload):
        self.calls.append((action, payload))
        return {"status": "success", "mode": "admin", "echo": action}


def make_agent(admin=None):
    # GraphAgent only touches jobs/pipeline/profiles/etc. on non-admin paths,
    # so None placeholders are fine for this routing test.
    return GraphAgent(jobs=None, pipeline=None, profile_store=None,
                      metrics_store=None, benchmark=None, profiler=None,
                      admin=admin)


def test_admin_action_routed_to_admin_handler():
    admin = StubAdmin()
    agent = make_agent(admin)
    out = agent.handle({"action": "admin_get_config", "admin_key": "k"}, "s1", "u1")
    assert out == {"status": "success", "mode": "admin", "echo": "admin_get_config"}
    assert admin.calls[0][0] == "admin_get_config"


def test_admin_action_without_admin_configured():
    agent = make_agent(admin=None)
    out = agent.handle({"action": "admin_get_config", "admin_key": "k"}, "s1", "u1")
    assert out["status"] == "error" and "not configured" in out["error"]


class StubJob:
    def __init__(self):
        self.job_id = "j1"
        self.status = "running"
        self.stage = "plan"
        self.activity = []
        self.result = None
        self.error = None


class StubJobs:
    def create(self, session, query):
        return StubJob()

    def save(self, job):
        pass


class StubPipeline:
    def __init__(self):
        self.deadline = None

    def advance(self, job, deadline=None):
        self.deadline = deadline


class StubProfiles:
    def get_active(self):
        return object()


def test_budget_s_caps_first_call_deadline():
    import time

    pipe = StubPipeline()
    agent = GraphAgent(jobs=StubJobs(), pipeline=pipe, profile_store=StubProfiles(),
                       metrics_store=None, benchmark=None, profiler=None,
                       request_budget_s=40.0)
    t0 = time.monotonic()
    out = agent.handle({"message": "why did my revenue drop last week?", "budget_s": 1},
                       "s1", "u1")
    assert out["job_id"] == "j1"
    assert pipe.deadline is not None and pipe.deadline - t0 < 5  # ~1s, not ~40s
