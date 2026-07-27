# Onboarding Agent — Evaluation Suite

Comprehensive evaluations for the `serve-onboarding-agent-service`, covering the full onboarding flow from welcome to handoff.

## Quick Start

```bash
cd serve-onboarding-agent-service

# Install test dependencies
pip install pytest pytest-asyncio pyyaml

# Run all evals
python -m pytest evals/ -v

# Run a specific layer
python -m pytest evals/test_profile_extractor.py -v
python -m pytest evals/test_eligibility_logic.py -v
python -m pytest evals/test_state_transitions.py -v
python -m pytest evals/test_onboarding_logic.py -v
python -m pytest evals/test_llm_prompts.py -v
python -m pytest evals/test_cross_domain_signals.py -v

# Generate JUnit XML report (for CI)
python -m pytest evals/ -v --junitxml=evals/results.xml
```

## Architecture

```
evals/
├── conftest.py                  # Shared fixtures: mocked MCP client, mocked LLM
├── test_cases.yaml              # Golden test cases (inputs + expected outputs)
├── test_profile_extractor.py    # Layer 1: Pure regex extraction
├── test_eligibility_logic.py    # Layer 1: Eligibility parsing logic
├── test_state_transitions.py    # Layer 1: Deterministic stage routing
├── test_cross_domain_signals.py # Layer 1: Preference signal extraction
├── test_llm_prompts.py          # Layer 2: Prompt construction verification
├── test_onboarding_logic.py     # Layer 3: Integration (mocked MCP + LLM)
└── README.md                    # This file
```

## Layers

| Layer | File | What it tests | LLM? | I/O? | Speed |
|-------|------|--------------|-------|------|-------|
| 1 | `test_profile_extractor.py` | Name/email/phone/qualification extraction from 30+ message formats | No | No | <1s |
| 1 | `test_eligibility_logic.py` | Bundled/individual eligibility, double-negative, keywords | No | No | <1s |
| 1 | `test_state_transitions.py` | All stage transitions, pause/resume, legacy redirect | No | No | <1s |
| 1 | `test_cross_domain_signals.py` | Subject/day/time/grade preference capture | No | No | <1s |
| 2 | `test_llm_prompts.py` | Prompt content, rules, field injection per stage | No | No | <1s |
| 3 | `test_onboarding_logic.py` | Full process_turn with mocked dependencies | No | Mocked | <2s |

**Total runtime: ~3-5 seconds** (all deterministic, no real LLM calls)

## Coverage Map

### Stages Covered

| Stage | Transitions | Prompt | Integration |
|-------|-------------|--------|-------------|
| welcome | ✅ First turn stays, second advances | ✅ Content + rules | ✅ Full turn |
| orientation_video | ✅ Ack → eligibility | ✅ Video tag | ✅ Full turn |
| eligibility_screening | ✅ Bundled yes/no, individual, fail | ✅ Bundled/individual/clarification | ✅ Full turn |
| contact_capture | ✅ All captured → review | ✅ Batched/single/typo/reluctance | ✅ Full turn |
| registration_review | ✅ Confirm/edit/unrelated | ✅ Field values + no-invent rule | ✅ Full turn |
| onboarding_complete | ✅ → handoff | ✅ Credentials + portal URL | ✅ Handoff + volunteer record |
| human_review | ✅ From eligibility fail | ✅ Transparent messaging | ✅ Via eligibility fail |
| paused | ✅ Pause/resume cycle | ✅ Progress saved message | ✅ Full turn |

### Scenarios Covered

| Scenario | Files |
|----------|-------|
| Happy path (full journey) | `test_onboarding_logic.py::TestHappyPath` |
| Hindi/Hinglish names | `test_profile_extractor.py::TestNameExtraction::test_hindi_signals` |
| Email typo detection | `test_profile_extractor.py::TestEmailTypoDetection`, `test_onboarding_logic.py::TestEmailTypoInTurn` |
| Reluctance handling | `test_eligibility_logic.py::TestReluctanceDetection`, `test_llm_prompts.py::TestContactCapturePrompt::test_reluctance_prompt` |
| Eligibility failure (underage) | `test_eligibility_logic.py::TestIndividualEligibility`, `test_onboarding_logic.py::TestEligibilityFailure` |
| Double-negative confirmation | `test_eligibility_logic.py::TestIndividualEligibility::test_double_negative_confirms_fail` |
| Phone auto-populate (WhatsApp) | `test_onboarding_logic.py::TestWhatsAppPhoneAutoPopulate` |
| Pause/resume | `test_state_transitions.py::TestPauseResume`, `test_onboarding_logic.py::TestPauseResumeInTurn` |
| Batched contact (name+email+phone) | `test_profile_extractor.py::TestBatchedExtraction`, `test_onboarding_logic.py::TestHappyPath::test_contact_capture_batched` |
| Cross-domain signals (preferences) | `test_cross_domain_signals.py`, `test_onboarding_logic.py::TestCrossDomainSignals` |
| Volunteer record creation | `test_onboarding_logic.py::TestCompletionVolunteerRecord` |
| Handoff to selection agent | `test_onboarding_logic.py::TestHappyPath::test_registration_confirmed_completes` |
| Sequential/same-digit phone rejection | `test_profile_extractor.py::TestPhoneExtraction` |
| Legacy stage normalization | `test_state_transitions.py::TestLegacyStageRedirect` |
| Sub-state serialization roundtrip | `test_state_transitions.py::TestSubStateSerialization` |

## Adding New Test Cases

### For profile extraction
Add to `test_profile_extractor.py` using parametrize:
```python
@pytest.mark.parametrize("message,expected", [
    ("Your new test case here", "Expected Name"),
])
def test_new_pattern(self, message, expected):
    result = profile_extractor._extract_name(message)
    assert result == expected
```

### For state transitions
Add to `test_state_transitions.py`:
```python
def test_your_scenario(self):
    sub = _sub(your_sub_state_overrides)
    state, reason = _determine_next_state("current_stage", "user message", confirmed_fields, sub)
    assert state == "expected_stage"
```

### For integration scenarios
Add to `test_onboarding_logic.py`:
```python
@pytest.mark.asyncio
async def test_your_scenario(self, session_id, mock_domain_client, mock_llm_adapter):
    # Set up MCP mock returns
    mock_domain_client.get_missing_fields.return_value = {...}
    # Set up LLM mock
    mock_llm_adapter.generate_response.return_value = "..."
    # Build request and call
    req, _ = _make_request(session_id, stage="...", user_message="...")
    response = await onboarding_agent_service.process_turn(req)
    # Assert
    assert response.state == "expected"
```

### For golden test cases (YAML)
Add to `test_cases.yaml` under the appropriate section. These can be loaded by tests using:
```python
import yaml
with open("evals/test_cases.yaml") as f:
    cases = yaml.safe_load(f)
```

## Interpreting Results

### All Passing
```
========================= 72 passed in 3.1s =========================
```
The onboarding agent's deterministic logic is working correctly.

### Failures
Each failure shows:
- **Test name**: Identifies the exact scenario that failed
- **Expected vs Actual**: What was expected and what the code produced
- **Location**: File and line number

Example:
```
FAILED test_profile_extractor.py::TestNameExtraction::test_hindi_signals[Mera naam Ravi Kumar hai-Ravi Kumar]
    AssertionError: Expected 'Ravi Kumar', got None
```
This means the Hindi name extraction regex failed for this input.

### Common Failure Causes
1. **Profile extraction failure** → Regex pattern needs updating
2. **State transition mismatch** → Logic in `_determine_next_state` has a bug
3. **Eligibility logic error** → `_apply_eligibility_answers` parsing issue
4. **Integration test failure** → MCP call order or field saving logic changed

## CI Integration

Add to your CI pipeline:
```yaml
- name: Run Onboarding Agent Evals
  run: |
    cd serve-onboarding-agent-service
    pip install -r requirements.txt
    pip install pytest pytest-asyncio pyyaml
    python -m pytest evals/ -v --junitxml=evals/results.xml
  
- name: Upload Test Results
  uses: actions/upload-artifact@v4
  with:
    name: onboarding-eval-results
    path: serve-onboarding-agent-service/evals/results.xml
```

## Design Decisions

1. **No real LLM calls** — All tests mock the LLM. We test that the *correct prompt* is constructed, not that Claude gives a good response. This keeps tests fast, cheap, and deterministic.

2. **No real MCP calls** — MCP client is fully mocked. We verify the *correct tools are called with correct arguments*, not that the MCP server works.

3. **Layer separation** — Pure logic tests (Layer 1) catch extraction/routing bugs instantly. Integration tests (Layer 3) verify the full orchestration flow.

4. **Golden test cases in YAML** — Non-engineers can review and extend test scenarios without touching Python code.

5. **Parametrized tests** — Each input/output pair is a separate test case in the report, making it easy to identify which exact pattern failed.
