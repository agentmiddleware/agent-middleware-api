
### 2026-10-03T00:35:34Z — resume-identity

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['python3', '-c', 'from pathlib import Path; import subprocess; print("Initial bootstrap command: pwd; read run_logged.py and COORDINATION-SESSION.md (completed successfully before logger use)"); [(print("COMMAND",a),subprocess.run(a)) for a in [["pwd"],["git","branch","--show-current"],["git","remote","get-url","origin"],["git","worktree","list"],["git","status","--short"]]]; [(print("FILE",p),print(Path(p).read_text())) for p in ["AGENTS.md","tests/AGENTS.md","pyproject.toml","requirements.txt","tests/conftest.py"]]']`

Outcome: exit 0; 0.1s; ended 2026-10-03T00:35:34Z. [Output](artifacts/backend-resume-identity.txt).

### 2026-10-03T00:35:39Z — concise-config

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['python3', '-c', 'from pathlib import Path; import subprocess; [(subprocess.run(a)) for a in [["git","branch","--show-current"],["git","remote","get-url","origin"],["git","worktree","list"],["git","status","--short"]]]; [(print("FILE",p),print(Path(p).read_text())) for p in ["tests/AGENTS.md","pyproject.toml","requirements.txt"]]; print("PYTHON", list(Path("/private/tmp").glob("*qa*"))); print("AGENTS",[str(x) for x in Path("app").rglob("AGENTS.md")])']`

Outcome: exit 0; 0.1s; ended 2026-10-03T00:35:39Z. [Output](artifacts/backend-concise-config.txt).

### 2026-10-03T00:35:44Z — install-python-qa

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['uv', 'venv', '--python', 'python3', '/private/tmp/amw-qa-python']`

Outcome: exit 0; 0.1s; ended 2026-10-03T00:35:44Z. [Output](artifacts/backend-install-python-qa.txt).

### 2026-10-03T00:35:44Z — install-runtime-test-deps

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['uv', 'pip', 'install', '--python', '/private/tmp/amw-qa-python/bin/python', '-r', 'requirements.txt', 'ruff', 'hypothesis', 'pip-audit', 'pytest-socket', 'openapi-spec-validator']`

Outcome: exit 0; 2.0s; ended 2026-10-03T00:35:46Z. [Output](artifacts/backend-install-runtime-test-deps.txt).

### 2026-10-03T00:35:50Z — suite-safety-map

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['python3', '-c', 'from pathlib import Path; import subprocess; print("Runtime deps present",Path("/private/tmp/amw-qa-python/bin/pytest").exists()); print("SKILL"); print(Path("/Users/sellers/.agents/skills/security-review/SKILL.md").read_text()); subprocess.run(["rg","-n","https?://|load_dotenv|env_file|socket|postgres|REDIS|subprocess|requests\\\\.","tests","app/core/config.py","app/db/database.py"]); print("TEST COUNT",len(list(Path("tests").rglob("test_*.py"))))']`

Outcome: exit 0; 0.0s; ended 2026-10-03T00:35:50Z. [Output](artifacts/backend-suite-safety-map.txt).

### 2026-10-03T00:35:58Z — safety-focused

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['python3', '-c', 'from pathlib import Path; import subprocess; print(Path("app/core/config.py").read_text()[-16000:]); subprocess.run(["rg","-n","load_dotenv|read_env_file|env_file|POSTGRES.*URL|TEST_DATABASE|LIVE_|RUN_.*INTEGRATION|subprocess\\\\.","app","tests","scripts/quickstart.py"]); print("DEPS LOG",Path("docs/qa/2026-10-02/artifacts/backend-install-runtime-test-deps.txt").read_text()[-2000:])']`

Outcome: exit 0; 0.1s; ended 2026-10-03T00:35:58Z. [Output](artifacts/backend-safety-focused.txt).

### 2026-10-03T00:36:09Z — subprocess-network-inventory

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['python3', '-c', 'from pathlib import Path; import subprocess; subprocess.run(["rg","-n","subprocess\\\\.|os\\\\.system|Popen|create_subprocess|load_dotenv|DotEnvSettingsSource|socket\\\\.socket|socket\\\\.create_connection","tests"]); print("SOCKET PLUGIN",Path("/private/tmp/amw-qa-python/lib/python3.13/site-packages/pytest_socket.py").read_text()[:15000]); print("TEST NAMES",[x.name for x in Path("tests").glob("test_*.py")])']`

Outcome: exit 1; 0.1s; ended 2026-10-03T00:36:09Z. [Output](artifacts/backend-subprocess-network-inventory.txt).

### 2026-10-03T00:36:25Z — safety-bootstrap-create

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['python3', '-c', 'from pathlib import Path; p=Path("docs/qa/2026-10-02/backend_safety"); p.mkdir(exist_ok=True); p.joinpath("sitecustomize.py").write_text("\\"\\"\\"QA-only guard inherited by Python child processes; never used by product.\\"\\"\\"\\nimport ipaddress\\nimport os\\nimport socket\\nimport sys\\n\\n# Suppress all dotenv I/O before importing app settings.\\nfrom pydantic_settings.sources import DotEnvSettingsSource\\nDotEnvSettingsSource._read_env_files = lambda self: {}\\nimport dotenv\\ndotenv.load_dotenv = lambda *args, **kwargs: False\\ndotenv.dotenv_values = lambda *args, **kwargs: {}\\n\\ndef local(host):\\n    if host == \\"localhost\\":\\n        return True\\n    try:\\n        return ipaddress.ip_address(host).is_loopback\\n    except ValueError:\\n        return False\\n\\ndef guard(event, args):\\n    if event in (\\"socket.connect\\", \\"socket.sendto\\"):\\n        address = args[1]\\n        if isinstance(address, tuple) and not local(address[0]):\\n            raise PermissionError(\\"QA guard: non-loopback network denied\\")\\n    if event == \\"socket.getaddrinfo\\" and args[0] is not None and not local(args[0]):\\n        raise PermissionError(\\"QA guard: external DNS denied\\")\\n    if event == \\"subprocess.Popen\\":\\n        executable = os.path.basename(str(args[0]))\\n        if executable in {\\"railway\\", \\"vercel\\", \\"fly\\", \\"supabase\\", \\"firebase\\", \\"curl\\", \\"wget\\"}:\\n            raise PermissionError(\\"QA guard: external command denied\\")\\n    if event == \\"open\\" and isinstance(args[0], (str, bytes)):\\n        name = os.path.basename(os.fsdecode(args[0]))\\n        if name == \\".env\\" or name.startswith(\\".env.\\"):\\n            raise PermissionError(\\"QA guard: environment file access denied\\")\\n\\nsys.addaudithook(guard)\\n"); print("Created inherited dotenv/network/command guard")']`

Outcome: exit 0; 0.0s; ended 2026-10-03T00:36:25Z. [Output](artifacts/backend-safety-bootstrap-create.txt).

### 2026-10-03T00:36:34Z — baseline-suite

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['env', 'PYTHONPATH=docs/qa/2026-10-02/backend_safety:.', 'DATABASE_URL=sqlite+aiosqlite:///./test.db', 'STATE_BACKEND=memory', 'TRUST_MODE_ENABLED=false', 'ALLOW_LEGACY_UNPERMITTED_MCP=true', 'COVERAGE_FILE=/private/tmp/amw-qa-baseline.coverage', '/private/tmp/amw-qa-python/bin/python', '-m', 'pytest', 'tests', '-q', '--tb=short', '--cov=app', '--cov-report=json:docs/qa/2026-10-02/artifacts/backend-baseline-coverage.json', '--cov-report=term', '--ignore=tests/test_prepare_railway_release.py', '--ignore=tests/test_railway_preflight.py', '--ignore=tests/test_railway_iac_config.py']`


### 2026-10-03T00:36:43Z — ruff-baseline

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['/private/tmp/amw-qa-python/bin/ruff', 'check', '.']`


### 2026-10-03T00:36:43Z — trust-test-inventory

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['python3', '-c', 'from pathlib import Path; import subprocess; print("CRITICAL TESTS",[x.name for x in Path("tests").glob("test_*.py") if any(s in x.name for s in ["trust","tenant","idempot","boundary","replay","dispatch","concur","upstream","negative","error","openapi"])]); subprocess.run(["rg","-n","^def test_|^async def test_|async def resolve|def resolve","tests/test_trust_negative_security.py","tests/test_tenant_isolation_hardening.py","tests/test_idempotency_key_contract.py","app/core/idempotency.py"]); print("APP INSTRUCTIONS",Path("app/services/AGENTS.md").read_text())']`


### 2026-10-03T00:36:43Z — mypy-baseline

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['/private/tmp/amw-qa-python/bin/mypy', 'app']`

Outcome: exit 0; 0.0s; ended 2026-10-03T00:36:43Z. [Output](artifacts/backend-trust-test-inventory.txt).
Outcome: exit 1; 0.5s; ended 2026-10-03T00:36:43Z. [Output](artifacts/backend-ruff-baseline.txt).
Outcome: exit 0; 7.6s; ended 2026-10-03T00:36:50Z. [Output](artifacts/backend-mypy-baseline.txt).

### 2026-10-03T00:36:57Z — fix-qa-guard-lint

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['python3', '-c', 'from pathlib import Path; p=Path("docs/qa/2026-10-02/backend_safety/sitecustomize.py"); p.write_text(p.read_text().replace("import socket\\n", "")); print("Removed unused import from QA harness only")']`

Outcome: exit 0; 0.1s; ended 2026-10-03T00:36:57Z. [Output](artifacts/backend-fix-qa-guard-lint.txt).

### 2026-10-03T00:37:12Z — idempotency-openapi-review

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['python3', '-c', 'from pathlib import Path; import subprocess; [(print("FILE",p),print(Path(p).read_text())) for p in ["tests/test_mcp_idempotency_key_validation.py","tests/test_idempotency.py"]]; subprocess.run(["rg","-n","resolve_client_idempotency_key|def.*idempotency|OpenAPI|openapi|Security\\\\(|APIKeyHeader|def verify_api_key","app","tests/test_api_keys.py","tests/test_trust_boundary.py"]); print("CORE",[p.name for p in Path("app/core").glob("*.py")])']`

Outcome: exit 0; 0.1s; ended 2026-10-03T00:37:13Z. [Output](artifacts/backend-idempotency-openapi-review.txt).

### 2026-10-03T00:37:17Z — request-boundary-source

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['python3', '-c', 'from pathlib import Path; import subprocess; subprocess.run(["rg","-n","resolve_client_idempotency_key|def.*idempotency|APIKeyHeader|def verify_api_key","app"]); [(print("FILE",p),print(Path(p).read_text())) for p in ["app/core/auth.py","app/services/request_keys.py"] if Path(p).exists()]']`

Outcome: exit 0; 0.0s; ended 2026-10-03T00:37:17Z. [Output](artifacts/backend-request-boundary-source.txt).

### 2026-10-03T00:37:36Z — key-validation-locate

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['rg', '-n', '-A', '100', '-B', '10', 'def resolve_client_idempotency_key', 'app']`

Outcome: exit 0; 0.0s; ended 2026-10-03T00:37:36Z. [Output](artifacts/backend-key-validation-locate.txt).

### 2026-10-03T00:37:36Z — openapi-contract-probe

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['env', 'PYTHONPATH=docs/qa/2026-10-02/backend_safety:.', 'TRUST_MODE_ENABLED=false', 'ALLOW_LEGACY_UNPERMITTED_MCP=true', 'DATABASE_URL=sqlite+aiosqlite:///./test.db', 'STATE_BACKEND=memory', '/private/tmp/amw-qa-python/bin/python', '-c', 'from app.main import app; from openapi_spec_validator import validate; from collections import Counter; import json; from pathlib import Path; schema=app.openapi(); validate(schema); ops=[(path,method,op) for path,item in schema["paths"].items() for method,op in item.items() if method in {"get","post","put","patch","delete"}]; dup=[key for key,n in Counter(op.get("operationId") for _,_,op in ops).items() if n>1]; print("OpenAPI validates; paths",len(schema["paths"]),"operations",len(ops),"duplicate operationIds",dup); print("securitySchemes",schema.get("components",{}).get("securitySchemes")); print("Endpoints",[(p,m,op.get("security")) for p,m,op in ops]); Path("docs/qa/2026-10-02/artifacts/backend-openapi-summary.json").write_text(json.dumps({"version":schema["openapi"],"paths":len(schema["paths"]),"operations":len(ops),"duplicates":dup,"securitySchemes":schema.get("components",{}).get("securitySchemes")},indent=2))']`

Outcome: exit 0; 3.1s; ended 2026-10-03T00:37:39Z. [Output](artifacts/backend-openapi-contract-probe.txt).

### 2026-10-03T00:37:40Z — focused-key-validation-source

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['sed', '-n', '1,153p', 'app/services/idempotency.py']`

Outcome: exit 0; 0.0s; ended 2026-10-03T00:37:40Z. [Output](artifacts/backend-focused-key-validation-source.txt).

### 2026-10-03T00:37:46Z — unicode-contract-tests-map

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['rg', '-n', 'surrogate|ud800|d800|utf8|unicode|Unicode', 'tests/test_mcp_idempotency_key_validation.py', 'tests/test_idempotency.py', 'app/services/signing_keys.py']`

Outcome: exit 1; 0.0s; ended 2026-10-03T00:37:46Z. [Output](artifacts/backend-unicode-contract-tests-map.txt).

### 2026-10-03T00:37:46Z — suite-progress

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['python3', '-c', 'from pathlib import Path; import subprocess; subprocess.run(["ps","-Ao","pid,etime,comm"]); p=Path("/private/tmp/amw-qa-baseline.coverage"); print("coverage_written",p.exists())']`

Outcome: exit 1; 0.0s; ended 2026-10-03T00:37:46Z. [Output](artifacts/backend-suite-progress.txt).

### 2026-10-03T00:38:00Z — new-test-fixtures

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['python3', '-c', 'from pathlib import Path; paths={"tests/test_mcp_idempotency_key_validation.py":(1,165),"tests/test_trust_negative_security.py":(1,83),"tests/trust_helpers.py":(1,230),"app/services/signing_keys.py":(1,100)}; [(print("FILE",p),print("\\n".join(f"{i+1}: {l}" for i,l in enumerate(Path(p).read_text().splitlines()) if a<=i+1<=b))) for p,(a,b) in paths.items() if Path(p).exists()]']`

Outcome: exit 0; 0.0s; ended 2026-10-03T00:38:00Z. [Output](artifacts/backend-new-test-fixtures.txt).

### 2026-10-03T00:38:43Z — add-risk-tests

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['python3', '-']`

Outcome: exit 0; 0.0s; ended 2026-10-03T00:38:43Z. [Output](artifacts/backend-add-risk-tests.txt).

### 2026-10-03T00:38:51Z — test-safety-annotations

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['python3', '-c', 'from pathlib import Path; import subprocess; subprocess.run(["rg","-n","skipif|DATABASE_URL|MIGRATIONS|POSTGRES|ALLOW_|RUN_|TEST_","tests/test_postgres_datetime_binding.py","tests/test_mcp_postgres_multiprocess.py","tests/test_duplicate_guard_postgres_concurrency.py","tests/test_permit_postgres_concurrency.py"]); print("CI workflows",[str(x) for x in Path(".github/workflows").glob("*.yml")])']`


### 2026-10-03T00:38:51Z — ruff-after-qa

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['/private/tmp/amw-qa-python/bin/ruff', 'check', '.']`

Outcome: exit 0; 0.0s; ended 2026-10-03T00:38:51Z. [Output](artifacts/backend-test-safety-annotations.txt).
Outcome: exit 0; 0.1s; ended 2026-10-03T00:38:51Z. [Output](artifacts/backend-ruff-after-qa.txt).

### 2026-10-03T00:39:04Z — owasp-controls-map

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['python3', '-c', 'from pathlib import Path; import subprocess; subprocess.run(["rg","-n","def |@router|LIMIT|MAX_|Response|status_code","app/middleware/request_body_limit.py","app/core/url_guard.py","app/core/rate_limiter.py","app/services/upstream_mcp.py"]); print("ROUTERS",[p.name for p in Path("app/routers").glob("*.py")]); print("CLAUSES",[x.name for x in Path("tests").glob("test_*.py") if any(s in x.name for s in ["auth","ssrf","size","body","jwt","rate","limit","url","guard","scope"])])']`

Outcome: exit 0; 0.0s; ended 2026-10-03T00:39:04Z. [Output](artifacts/backend-owasp-controls-map.txt).

### 2026-10-03T00:39:14Z — owasp-source-read

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['python3', '-c', 'from pathlib import Path; paths={"app/middleware/request_body_limit.py":(1,140),"app/core/url_guard.py":(1,160),"tests/test_route_auth_inventory.py":(1,200),"app/core/auth.py":(20,95)}; [(print("FILE",p),print("\\n".join(f"{i+1}: {line}" for i,line in enumerate(Path(p).read_text().splitlines()) if a<=i+1<=b))) for p,(a,b) in paths.items()]']`

Outcome: exit 0; 0.0s; ended 2026-10-03T00:39:14Z. [Output](artifacts/backend-owasp-source-read.txt).

### 2026-10-03T00:39:20Z — ssrf-address-boundaries

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['env', 'PYTHONPATH=docs/qa/2026-10-02/backend_safety:.', 'TRUST_MODE_ENABLED=false', 'ALLOW_LEGACY_UNPERMITTED_MCP=true', '/private/tmp/amw-qa-python/bin/python', '-c', 'import asyncio, ipaddress; from app.core.url_guard import check_outbound_url; from pathlib import Path; import subprocess; addresses=["127.0.0.1","169.254.169.254","10.0.0.1","100.64.0.1","0.0.0.0","224.0.0.1","239.255.255.250","ff02::1","ff05::1","::1"]; async def_dummy=None']`

Outcome: exit 1; 0.2s; ended 2026-10-03T00:39:20Z. [Output](artifacts/backend-ssrf-address-boundaries.txt).

### 2026-10-03T00:39:27Z — ssrf-address-boundaries-retry

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['env', 'PYTHONPATH=docs/qa/2026-10-02/backend_safety:.', 'TRUST_MODE_ENABLED=false', 'ALLOW_LEGACY_UNPERMITTED_MCP=true', '/private/tmp/amw-qa-python/bin/python', '-']`

Outcome: exit 0; 0.2s; ended 2026-10-03T00:39:28Z. [Output](artifacts/backend-ssrf-address-boundaries-retry.txt).

### 2026-10-03T00:39:28Z — upstream-private-target-controls

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['sed', '-n', '335,415p', 'app/services/upstream_mcp.py']`

Outcome: exit 0; 0.0s; ended 2026-10-03T00:39:28Z. [Output](artifacts/backend-upstream-private-target-controls.txt).

### 2026-10-03T00:39:51Z — upstream-config-constructor

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['sed', '-n', '160,232p', 'app/services/upstream_mcp.py']`

Outcome: exit 0; 0.0s; ended 2026-10-03T00:39:51Z. [Output](artifacts/backend-upstream-config-constructor.txt).

### 2026-10-03T00:39:51Z — safety-subprocess-details

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['python3', '-c', 'from pathlib import Path; paths={"tests/test_minimal_path_e2e.py":(30,115),"tests/test_quickstart_path.py":(30,105),"tests/test_failure_lab.py":(1,58),"tests/test_partner_mcp.py":(210,240),"tests/test_site_agent_interface.py":(130,170)}; [(print("FILE",p),print("\\n".join(f"{i+1}: {line}" for i,line in enumerate(Path(p).read_text().splitlines()) if a<=i+1<=b))) for p,(a,b) in paths.items()]']`

Outcome: exit 0; 0.0s; ended 2026-10-03T00:39:51Z. [Output](artifacts/backend-safety-subprocess-details.txt).

### 2026-10-03T00:40:16Z — strengthen-python-child-isolation

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['/private/tmp/amw-qa-python/bin/python', '-']`

Outcome: exit 0; 0.0s; ended 2026-10-03T00:40:16Z. [Output](artifacts/backend-strengthen-python-child-isolation.txt).

### 2026-10-03T00:40:16Z — child-isolation-negative-control

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['env', 'PYTHONPATH=.', '/private/tmp/amw-qa-python/bin/python', '-']`

Outcome: exit 0; 0.2s; ended 2026-10-03T00:40:17Z. [Output](artifacts/backend-child-isolation-negative-control.txt).

### 2026-10-03T00:40:44Z — add-multicast-boundaries

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['python3', '-']`

Outcome: exit 0; 0.0s; ended 2026-10-03T00:40:44Z. [Output](artifacts/backend-add-multicast-boundaries.txt).

### 2026-10-03T00:41:12Z — surrogate-route-repro

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['env', 'PYTHONPATH=docs/qa/2026-10-02/backend_safety:.', 'DATABASE_URL=sqlite+aiosqlite:////private/tmp/amw-qa-surrogate-repro.db', 'STATE_BACKEND=memory', 'ALLOW_METADATA_CREATE_ALL=true', 'TRUST_MODE_ENABLED=false', 'ALLOW_LEGACY_UNPERMITTED_MCP=true', '/private/tmp/amw-qa-python/bin/python', '-']`

Outcome: exit 0; 2.3s; ended 2026-10-03T00:41:15Z. [Output](artifacts/backend-surrogate-route-repro.txt).

### 2026-10-03T00:41:37Z — surrogate-transport-guard-source

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['rg', '-n', '-A', '35', '-B', '12', 'Invalid JSON|await request.json|MCPContext', 'app/routers/mcp.py']`

Outcome: exit 0; 0.0s; ended 2026-10-03T00:41:37Z. [Output](artifacts/backend-surrogate-transport-guard-source.txt).

### 2026-10-03T00:41:57Z — retire-disproved-surrogate-finding

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['python3', '-']`

Outcome: exit 0; 0.0s; ended 2026-10-03T00:41:57Z. [Output](artifacts/backend-retire-disproved-surrogate-finding.txt).

### 2026-10-03T00:42:26Z — runtime-progress-and-charter

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['python3', '-']`


### 2026-10-03T00:42:26Z — exploratory charter BE-X1

30-minute boundary investigation alongside the isolated baseline run: challenge replay identity encoding, protected-route credentials, OpenAPI security metadata, outbound destination classification, and OWASP API controls. Success means either a minimal reproducible defect with no real external calls or evidence disproving the candidate. Surrogate-key candidate was disproved by HTTP 400 plus unchanged effect/debit/count snapshot; retained passing regression. Multicast destination acceptance and omitted Bearer security scheme are confirmed local contract gaps, pending full test confirmation.
Outcome: exit 0; 0.0s; ended 2026-10-03T00:42:26Z. [Output](artifacts/backend-runtime-progress-and-charter.txt).

### 2026-10-03T00:42:35Z — sdk-production-gates

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['python3', '-c', 'from pathlib import Path; import subprocess; subprocess.run(["rg","-n","pytest|production_trust|TRUST_MODE_ENABLED|TRUST_SIGNING|ENABLE_PROOF|cov",".github/workflows/ci.yml"]); print("SDK tests",[str(x) for r in [Path("b2a_sdk"),Path("wrappers")] for x in r.rglob("test_*.py")]); print("SDK manifests",[(str(p),p.read_text()) for r in [Path("b2a_sdk"),Path("wrappers")] for p in r.rglob("pyproject.toml")])']`

Outcome: exit 0; 0.0s; ended 2026-10-03T00:42:35Z. [Output](artifacts/backend-sdk-production-gates.txt).
Outcome: exit 1; 364.1s; ended 2026-10-03T00:42:38Z. [Output](artifacts/backend-baseline-suite.txt).

### 2026-10-03T00:43:08Z — backend-report-draft

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['python3', '-']`

Outcome: exit 0; 0.0s; ended 2026-10-03T00:43:08Z. [Output](artifacts/backend-backend-report-draft.txt).

### 2026-10-03T00:43:34Z — numeric-address-guard-calibration

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['python3', '-']`

Outcome: exit 0; 0.0s; ended 2026-10-03T00:43:35Z. [Output](artifacts/backend-numeric-address-guard-calibration.txt).

### 2026-10-03T00:43:35Z — baseline-final

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['env', 'PYTHONPATH=docs/qa/2026-10-02/backend_safety:.', 'DATABASE_URL=sqlite+aiosqlite:///./test.db', 'STATE_BACKEND=memory', 'TRUST_MODE_ENABLED=false', 'ALLOW_LEGACY_UNPERMITTED_MCP=true', 'COVERAGE_FILE=/private/tmp/amw-qa-baseline-final.coverage', '/private/tmp/amw-qa-python/bin/python', '-m', 'pytest', 'tests', '-q', '--tb=short', '--cov=app', '--cov-report=json:docs/qa/2026-10-02/artifacts/backend-baseline-final-coverage.json', '--cov-report=term', '--ignore=tests/test_qa_20261002_backend.py', '--ignore=tests/test_prepare_railway_release.py', '--ignore=tests/test_railway_preflight.py', '--ignore=tests/test_railway_iac_config.py', '-k', 'not test_signing_seed_is_a_visible_required_key and not test_signing_seed_ships_empty_rather_than_with_a_real_value and not test_env_example_documents_how_to_generate_the_seed and not test_default_state_backend_boots_locally']`


### 2026-10-03T00:43:47Z — baseline-failure-classification

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['python3', '-']`

Outcome: exit 0; 0.0s; ended 2026-10-03T00:43:47Z. [Output](artifacts/backend-baseline-failure-classification.txt).

### 2026-10-03T00:44:14Z — sdk-import-safety

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['python3', '-c', 'from pathlib import Path; import subprocess; subprocess.run(["rg","-n","^(import|from) |https?://|subprocess|Popen","b2a_sdk/tests","wrappers/openai-agent-middleware/tests","wrappers/autogen-agent-middleware/tests","wrappers/crewai-agent-middleware/tests","wrappers/langchain-agent-middleware/tests"]); print("CI SDK command", "\\n".join(Path(".github/workflows/ci.yml").read_text().splitlines()[295:325]))']`

Outcome: exit 0; 0.1s; ended 2026-10-03T00:44:14Z. [Output](artifacts/backend-sdk-import-safety.txt).

### 2026-10-03T00:44:35Z — wrapper-runtime-imports

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['rg', '-n', '^(import|from)|except ImportError', 'wrappers/autogen-agent-middleware/src', 'wrappers/crewai-agent-middleware/src', 'wrappers/langchain-agent-middleware/src', 'wrappers/openai-agent-middleware/src']`

Outcome: exit 0; 0.0s; ended 2026-10-03T00:44:35Z. [Output](artifacts/backend-wrapper-runtime-imports.txt).

### 2026-10-03T00:44:53Z — posture-test-environment

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['python3', '-c', 'from pathlib import Path; print("\\n".join(Path("tests/test_production_trust_posture.py").read_text().splitlines()[:145])); print("CI STRICT ENV"); print("\\n".join(Path(".github/workflows/ci.yml").read_text().splitlines()[430:450]))']`

Outcome: exit 0; 0.0s; ended 2026-10-03T00:44:53Z. [Output](artifacts/backend-posture-test-environment.txt).

### 2026-10-03T00:45:10Z — branch-diff-scope

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['git', 'status', '--short']`

Outcome: exit 0; 0.0s; ended 2026-10-03T00:45:10Z. [Output](artifacts/backend-branch-diff-scope.txt).

### 2026-10-03T00:45:10Z — sdk-wheel-install

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['uv', 'pip', 'install', '--python', '/private/tmp/amw-qa-python/bin/python', '--no-deps', './b2a_sdk', './wrappers/openai-agent-middleware']`

Outcome: exit 0; 0.7s; ended 2026-10-03T00:45:11Z. [Output](artifacts/backend-sdk-wheel-install.txt).

### 2026-10-03T00:45:35Z — ruff-current-qa

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['/private/tmp/amw-qa-python/bin/ruff', 'check', '.']`

Outcome: exit 0; 0.0s; ended 2026-10-03T00:45:35Z. [Output](artifacts/backend-ruff-current-qa.txt).

### 2026-10-03T00:46:03Z — report-scope-clarifications

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['python3', '-']`

Outcome: exit 0; 0.0s; ended 2026-10-03T00:46:03Z. [Output](artifacts/backend-report-scope-clarifications.txt).

### 2026-10-03T00:47:11Z — checkpoint-baseline-final

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['python3', '-']`

Outcome: exit 0; 0.0s; ended 2026-10-03T00:47:11Z. [Output](artifacts/backend-checkpoint-baseline-final.txt).
Outcome: exit 0; 338.8s; ended 2026-10-03T00:49:13Z. [Output](artifacts/backend-baseline-final.txt).

### 2026-10-03T00:49:16Z — added-tests

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['env', 'PYTHONPATH=docs/qa/2026-10-02/backend_safety:.', 'DATABASE_URL=sqlite+aiosqlite:///./test.db', 'STATE_BACKEND=memory', 'TRUST_MODE_ENABLED=false', 'ALLOW_LEGACY_UNPERMITTED_MCP=true', '/private/tmp/amw-qa-python/bin/python', '-m', 'pytest', 'tests/test_qa_20261002_backend.py', '-q', '-rx', '--tb=short']`

Outcome: exit 0; 4.8s; ended 2026-10-03T00:49:21Z. [Output](artifacts/backend-added-tests.txt).

### 2026-10-03T00:49:27Z — after-full

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['env', 'PYTHONPATH=docs/qa/2026-10-02/backend_safety:.', 'DATABASE_URL=sqlite+aiosqlite:///./test.db', 'STATE_BACKEND=memory', 'TRUST_MODE_ENABLED=false', 'ALLOW_LEGACY_UNPERMITTED_MCP=true', 'COVERAGE_FILE=/private/tmp/amw-qa-after.coverage', '/private/tmp/amw-qa-python/bin/python', '-m', 'pytest', 'tests', '-q', '-rs', '--tb=short', '--cov=app', '--cov-report=json:docs/qa/2026-10-02/artifacts/backend-after-coverage.json', '--cov-report=term', '--ignore=tests/test_prepare_railway_release.py', '--ignore=tests/test_railway_preflight.py', '--ignore=tests/test_railway_iac_config.py', '-k', 'not test_signing_seed_is_a_visible_required_key and not test_signing_seed_ships_empty_rather_than_with_a_real_value and not test_env_example_documents_how_to_generate_the_seed and not test_default_state_backend_boots_locally']`


### 2026-10-03T00:49:49Z — optional-framework-availability

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['/private/tmp/amw-qa-python/bin/python', '-c', 'import importlib.util; print({name: importlib.util.find_spec(name) is not None for name in ["autogen","crewai","langchain_core","langgraph","openai_b2a","b2a_sdk"]})']`

Outcome: exit 0; 0.1s; ended 2026-10-03T00:49:49Z. [Output](artifacts/backend-optional-framework-availability.txt).

### 2026-10-03T00:49:49Z — report-confirm-added-tests

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['python3', '-']`

Outcome: exit 0; 0.0s; ended 2026-10-03T00:49:49Z. [Output](artifacts/backend-report-confirm-added-tests.txt).

### 2026-10-03T00:51:08Z — dependency-consistency

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['/private/tmp/amw-qa-python/bin/python', '-m', 'pip', 'check']`

Outcome: exit 0; 0.4s; ended 2026-10-03T00:51:08Z. [Output](artifacts/backend-dependency-consistency.txt).

### 2026-10-03T00:54:08Z — after-checkpoint

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['python3', '-']`

Outcome for `backend-after-checkpoint`: exit 0; 0.0s; ended 2026-10-03T00:54:08Z. [Output](artifacts/backend-after-checkpoint.txt).
Outcome: exit 0; 309.7s; ended 2026-10-03T00:54:37Z. [Output](artifacts/backend-after-full.txt).

### 2026-10-03T00:55:02Z — python-sdk-installed-tests

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api/b2a_sdk`

Command (argv): `['env', 'PYTHONPATH=', 'COVERAGE_FILE=/private/tmp/amw-qa-sdk.coverage', '/private/tmp/amw-qa-python/bin/python', '-m', 'pytest', '-c', 'pyproject.toml', '--rootdir=.', '--confcutdir=.', '-o', 'pythonpath=', 'tests', '-q', '--tb=short', '--cov=b2a_sdk', '--cov-report=json:/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api/docs/qa/2026-10-02/artifacts/backend-sdk-coverage.json', '--cov-report=term']`

Outcome for `backend-python-sdk-installed-tests`: exit 0; 2.0s; ended 2026-10-03T00:55:04Z. [Output](artifacts/backend-python-sdk-installed-tests.txt).

### 2026-10-03T00:55:23Z — openai-wrapper-installed-tests

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api/wrappers/openai-agent-middleware`

Command (argv): `['env', 'PYTHONPATH=', 'COVERAGE_FILE=/private/tmp/amw-qa-openai-wrapper.coverage', '/private/tmp/amw-qa-python/bin/python', '-m', 'pytest', '-c', 'pyproject.toml', '--rootdir=.', '--confcutdir=.', '-o', 'pythonpath=', '-o', 'asyncio_mode=auto', 'tests', '-q', '--tb=short', '--cov=openai_b2a', '--cov-report=json:/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api/docs/qa/2026-10-02/artifacts/backend-openai-wrapper-coverage.json', '--cov-report=term']`

Outcome for `backend-openai-wrapper-installed-tests`: exit 0; 1.2s; ended 2026-10-03T00:55:24Z. [Output](artifacts/backend-openai-wrapper-installed-tests.txt).

### 2026-10-03T00:55:31Z — production-posture-local

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['/private/tmp/amw-qa-python/bin/python', '-']`

Outcome for `backend-production-posture-local`: exit 0; 5.2s; ended 2026-10-03T00:55:36Z. [Output](artifacts/backend-production-posture-local.txt).

### 2026-10-03T00:55:41Z — coverage-comparison

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['python3', '-']`

Outcome for `backend-coverage-comparison`: exit 0; 0.0s; ended 2026-10-03T00:55:41Z. [Output](artifacts/backend-coverage-comparison.txt).

### 2026-10-03T00:56:17Z — finalize-backend-report

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['python3', '-']`


### 2026-10-03T00:56:17Z — backend charter completion

BE-X1 completed: validated auth/contract/Unicode/IP boundaries; rejected surrogate-key candidate with HTTP400 and unchanged effects/state; confirmed BE-002 and BE-003 Low via seven strict xfails. Final local app suite: 3655 passed,60 skipped,4 deselected,7 xfailed; baseline3628 passed. Before/after coverage21249/24266=87.566966%,unchanged. SDK129 passed; OpenAI wrapper65 passed; production-posture12 passed. Ruff/mypy/dependency consistency passed. No product code changed. All failures/dead ends and task-boundary exclusions retained above.
Outcome for `backend-finalize-backend-report`: exit 0; 0.0s; ended 2026-10-03T00:56:17Z. [Output](artifacts/backend-finalize-backend-report.txt).

### 2026-10-03T00:56:17Z — final-backend-lint

CWD: `/Users/sellers/Projects/qa-sweep-2026-10-02/agent-middleware-api`

Command (argv): `['/private/tmp/amw-qa-python/bin/ruff', 'check', 'tests/test_qa_20261002_backend.py', 'docs/qa/2026-10-02/backend_safety']`

Outcome for `backend-final-backend-lint`: exit 0; 0.0s; ended 2026-10-03T00:56:17Z. [Output](artifacts/backend-final-backend-lint.txt).
