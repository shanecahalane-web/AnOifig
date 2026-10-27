# Provider deadline investigation

The production provider implementation is unchanged. No provider lifecycle defect was confirmed.

## Original failure and measurements

Using the exact reviewed development image `anoifig-independent-review:development`, the original DNS case failed at `dns_started` in 2.05 seconds in a network-disabled container. The parent returned on its two-second deadline; the child was stopped. The failure was that the harness had not reached the intended fault stage.

The default managed Docker proxy is a numeric IP address. HTTPX can use it without DNS resolution, so replacing `socket.getaddrinfo` did not necessarily intercept any connection attempt. Proxy rejection could complete the child before the test's resolver fault. This is a harness dependency on ambient networking, not evidence of a production deadline overrun.

A scratch copy of the original helper logged monotonic timestamps around imports, client construction and `_completion` without changing production code. In one cold run, relative to parent entry:

| Stage | Seconds |
|---|---:|
| helper started | 0.080 |
| provider transport / SDK imported | 1.419 |
| SDK client constructed | 1.505 |
| full structured completion began | 1.506 |
| mocked resolver entered | 1.980 |
| parent returned and child stopped | 2.006 |

A warm run reached the resolver in 1.028 seconds. Thus cold SDK/interpreter setup plus strict tool/schema construction leaves essentially no resolver exercise time in a two-second test and can lose that event under ordinary scheduling. The complete elapsed-time safety boundary still held.

## Test-only correction

The DNS scenarios now inject an HTTPX client with an explicit synthetic invalid-host proxy, `trust_env=False` for this fault transport only, and normal TLS verification. Environment forwarding in production is untouched and its existing assertions remain.

The DNS scenarios call a minimal real SDK completion request through the existing `OpenAITransport.respond` context. This retains actual HTTPX resolution, asyncio resolver threads, SDK client teardown and parent process lifecycle, while excluding expensive structured-tool schema generation unrelated to the DNS fault. Full structured serialization/parsing and payload assertions remain in the existing component and isolated-success tests.

Two new startup-stall scenarios independently prove that the same unmodified two-second parent deadline includes setup/import time, including a child ignoring SIGTERM. Two new proxy variants prove that the DNS scenario no longer depends on ambient textual versus numeric proxy configuration.

No timeout was increased. Every original isolation-test assertion remains byte-identical. No production provider module, API, grant, dependency or configuration was changed.

## Evidence and commands

Original reviewed helper:
- Host isolation tests: 13 passed in 12.66s (run with local asyncio sockets permitted).
- New harness controls: 4 failed in 4.84s before helper changes.
- Original Docker DNS case: 1 failed in 2.05s at the `dns_started` assertion.

Candidate helper in an isolated, network-disabled Docker container:
- Original isolation tests plus new controls: 17 passed in 22.31s.

A reproducible original-case command (the image contains the reviewed files):

```sh
docker run --rm --network none \
  -e HTTPS_PROXY=http://synthetic-proxy.invalid:8080 \
  -e https_proxy=http://synthetic-proxy.invalid:8080 \
  anoifig-independent-review:development uv run --no-sync pytest -q \
  'tests/unit/test_tara_provider_isolation.py::test_deadline_bounds_real_resolver_retry_and_uncancellable_transport[dns]'
```

The complete post-fix provider command is:

```sh
uv run --frozen pytest -q tests/unit/test_tara_provider.py \
  tests/unit/test_tara_provider_isolation.py tests/unit/test_tara_provider_harness.py
```

Run the equivalent command in the rebuilt development image with `--network none`. The controlled DNS transport and all synthetic credentials remain offline. The unchanged production adapter still counts all startup and SDK work against its configured deadline.

Final helper/new-test validation:
- Host original provider tests plus new controls: **74 passed in 23.98s**.
- Fresh network-disabled Docker container, selecting the two-second DNS case first before the complete provider files: **74 passed in 26.29s**.
- Ruff lint and format passed for the changed helper/new module.
- Existing `test_tara_provider_isolation.py`, `test_tara_provider.py` and `tara_provider_parent.py` compare byte-for-byte equal to the reviewed commit.
- Repository edits are restricted to `tests/helpers/tara_provider_child.py` and new `tests/unit/test_tara_provider_harness.py`.

The full Milestone 3 validation and exact corrected-head CI result are recorded in [the validation report](03-tara-validation.md) and PR #4. Diagnostic logs are local evidence rather than repository artifacts.
