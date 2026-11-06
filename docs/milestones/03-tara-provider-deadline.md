# Provider deadline investigation

The production provider process, deadline, environment allowlist, bounded IPC and
termination/reaping code are unchanged. The test harness now distinguishes
transport-fault entry from cold-start containment.

## Independent evidence

The original correction at `dec21d05` forced a synthetic hostname proxy so ambient
numeric proxies could not bypass the injected DNS fault. It also replaced the DNS
scenario's completion method with a minimal SDK request. Independent review still
observed setup-dependent failures: focused host tests were 66 passed / 8 failed,
packaged provider tests were 65 passed / 9 failed, and the full host suite later
passed all 2,583 cases. Import timing was about 9.78 seconds cold and 2.84 seconds
on a repeat in that environment. The parent deadline and child-death assertions
passed before the missing fault-entry event assertions failed.

The follow-up reproduced this variability: the unmodified provider selection was
73 passed / 1 failed at `dns_started` for the SIGTERM-resistant DNS case. A passing
warm run alone therefore cannot establish reliable cold fault entry in two seconds.

## Test preparation and retained safety boundaries

For success, DNS, uncancellable transport and retry scenarios, `launch` starts a
test child and waits for a readiness pipe before the test starts its timer. The
child installs parent-death protection first, imports the real SDK and strict
schemas, loads its lazy completion resource, and closes a client without sending
a request. Preparation has its own 20-second fixture limit; failure to prepare
fails the test. Fixtures kill/reap and close prepared resources after each test.

The real application adapter then hands its payload to that child and enforces
its existing deadline. A bounded anonymous test descriptor transfers the result
to the production adapter's descriptor; malformed and oversized IPC tests retain
the original direct path. No database, messaging or unreviewed environment values
are added to the child. The readiness descriptor carries one byte and is closed.

The parent-death harness also relays this readiness signal before its original
five-second DNS-entry window starts. The separate worker retains its 30-second
provider deadline; the test retains its two-second parent/child termination
windows and all original assertions. This addresses a reproduced clean-image
failure (75 passed / 1 failed) in which cold setup never reached DNS within the
old readiness window. The outer fixture has a 25-second setup bound and fails
if the helper does not signal readiness.

The DNS helper now uses the complete production `OpenAITransport._completion`,
including strict tool/reply schemas. Its earlier minimal completion substitution
is removed. HTTPX still uses a synthetic hostname proxy and the injected resolver
stalls offline. Success/retry/late scenarios use the actual SDK with MockTransport.

The meaning of the timed fault tests is now explicit: after fixture preparation,
the real SDK must reach the selected fault and the production parent must contain
it within the original two-second budget plus the original cleanup allowance.
They no longer assume cold SDK setup can always reach DNS inside two seconds.
This is a change to the fault-entry setup assumption, not a claim about cold-start
latency.

Cold `startup` and `startup_ignore_term` scenarios remain unprepared and retain
their original two-second elapsed, SIGKILL, reaping and no-late-event assertions.
The production launcher/environment, parent-death, invalid IPC and oversized
input assertions remain. A new cold full-transport positive control uses a
20-second configured request budget; it verifies successful strict serialization
without fixture preparation. A second new control proves preparation emits no
SDK request or DNS event before the actual invocation.

An AST comparison against `dec21d05` found no removed or changed pre-existing
`assert` statements. The provider assertion modules have fixture/import additions;
they are not claimed to be byte-identical. No production timeout or safety
threshold was increased. The original cold-start containment assertions remain
separate from the prepared transport-fault measurements.

## Validation

The first prepared provider replay passed all 74 existing cases, DNS first, in
40.10 seconds. The complete host and packaged results, including the two added
controls, are recorded in the [follow-up validation](03-tara-re-review-corrections.md).

```sh
uv run --frozen pytest -q \
  'tests/unit/test_tara_provider_isolation.py::test_deadline_bounds_real_resolver_retry_and_uncancellable_transport[dns]' \
  tests/unit/test_tara_provider.py \
  tests/unit/test_tara_provider_isolation.py \
  tests/unit/test_tara_provider_harness.py
```

Run the same selection in a freshly built development image with `--network none`.
All requests use synthetic data and offline transport. No live provider is connected.

## Production limits

Production still counts process startup, imports, SDK setup, transport and parsing
against one configured deadline. Slow cold starts can therefore produce a safe
provider failure before a network call begins. Appropriate capacity and realistic
staging/load evaluation remain required. OS scheduling, process creation and
uninterruptible kernel work are not hard real-time guarantees; killing a local
child cannot undo a request already accepted remotely or its cost. These limits
are not resolved by a green fault-injection suite.
