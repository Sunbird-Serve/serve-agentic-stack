# Requirements Document

## Introduction

This document defines the requirements for the Recommended Volunteer Workflow — a parallel engagement path for volunteers who arrive via referral/recommendation. The workflow handles identity verification, preference gathering, and handoff to the fulfillment agent, all without modifying existing engagement code paths.

## Glossary

- **Orchestrator**: The central coordination service (`serve-orchestrator`) that resolves personas, manages sessions, and routes requests to agents.
- **Persona_Resolver**: The component within the Orchestrator that classifies inbound messages into persona types based on message content, trigger type, and actor lookup.
- **Engagement_Agent**: The agent service (`serve-engagement-agent-service`) that handles volunteer re-engagement and recommended volunteer workflows via separate handler classes.
- **RecommendedVolunteerHandler**: A parallel handler class within the Engagement Agent that processes the recommended volunteer workflow, completely separate from the existing `EngagementAgentService`.
- **Fulfillment_Agent**: The agent service (`serve-fulfillment-agent-service`) that matches volunteers to teaching needs.
- **MCP_Server**: The backend domain service (`serve-mcp-server`) that provides tools for volunteer lookup, session management, and event logging.
- **FulfillmentHandoffPayload**: The Pydantic model defining the data shape passed from the Engagement Agent to the Fulfillment Agent during handoff.
- **Registration_URL**: A configurable URL (default `https://up.serve.net.in`) where unregistered volunteers are directed to sign up.
- **Recommended_Volunteer**: A person who arrives saying they were recommended or referred, but has no prior fulfillment history in the system.
- **Engagement_Context**: The volunteer profile and history data returned by the MCP Server's `get_engagement_context` or `get_engagement_context_by_email` tools.
- **Sub_State**: A JSON-serialized dictionary persisted per session that tracks workflow-specific progress (identity verification status, preferences, handoff data).
- **Signal_Outcome**: A tool call made by the LLM to indicate a terminal decision (ready, not_registered, deferred, declined).

## Requirements

### Requirement 1: Persona Detection for Recommended Volunteers

**User Story:** As a recommended volunteer, I want the system to recognize that I arrived via a referral, so that I am routed to the correct workflow instead of the generic onboarding flow.

#### Acceptance Criteria

1. WHEN a user's first message contains a recommendation phrase in English, Hindi, or Hinglish (e.g., "I was recommended", "mujhe recommend kiya gaya", "referred by", "kisi ne bataya"), THE Persona_Resolver SHALL classify the user as `RECOMMENDED_VOLUNTEER` with confidence 0.95.
2. WHEN a user's first message matches both a returning volunteer pattern and a recommendation pattern, THE Persona_Resolver SHALL classify the user as `RETURNING_VOLUNTEER` because the returning volunteer check is evaluated first.
3. WHEN a channel sends an explicit `persona=recommended_volunteer` override, THE Orchestrator SHALL use `RECOMMENDED_VOLUNTEER` as the persona without running phrase detection.
4. WHEN the Persona_Resolver classifies a user as `RECOMMENDED_VOLUNTEER`, THE Orchestrator SHALL create a session with `workflow=recommended_volunteer` and route to the Engagement_Agent.

### Requirement 2: Session and Routing for Recommended Volunteer Workflow

**User Story:** As a system operator, I want recommended volunteer sessions to be routed correctly through the orchestrator, so that they reach the dedicated handler without interfering with existing workflows.

#### Acceptance Criteria

1. WHEN a session has `workflow=recommended_volunteer`, THE Orchestrator SHALL route all requests to the Engagement_Agent.
2. WHEN the Engagement_Agent receives a request with `workflow=recommended_volunteer`, THE Engagement_Agent SHALL dispatch it to the RecommendedVolunteerHandler instead of the existing EngagementAgentService.
3. WHEN the Engagement_Agent receives a request with `workflow=returning_volunteer`, THE Engagement_Agent SHALL dispatch it to the existing EngagementAgentService with no changes to its behavior.
4. THE Workflow_Validator SHALL define the `recommended_volunteer` workflow with stages: `verifying_identity`, `gathering_preferences`, `active`, `complete`, `not_registered`, `human_review`, and `paused`.
5. THE Workflow_Validator SHALL treat `not_registered` and `human_review` as terminal stages for the `recommended_volunteer` workflow.

### Requirement 3: Identity Verification via Phone Lookup

**User Story:** As a recommended volunteer, I want the system to verify my identity by looking up my phone number, so that it can confirm I am registered and personalize my experience.

#### Acceptance Criteria

1. WHEN the RecommendedVolunteerHandler is in the `verifying_identity` stage, THE RecommendedVolunteerHandler SHALL ask the volunteer for their phone number and call `get_engagement_context` via the MCP_Server.
2. WHEN `get_engagement_context` returns `status=success`, THE RecommendedVolunteerHandler SHALL set `identity_verified=true` in the Sub_State, cache the Engagement_Context, and advance to the `gathering_preferences` stage.
3. WHEN `get_engagement_context` returns `status=not_found`, THE RecommendedVolunteerHandler SHALL ask the volunteer for their registered email as a fallback.

### Requirement 4: Identity Verification via Email Fallback

**User Story:** As a recommended volunteer whose phone number is not found, I want to provide my email address as an alternative, so that the system can still verify my identity.

#### Acceptance Criteria

1. WHEN the phone lookup fails and the volunteer provides an email, THE RecommendedVolunteerHandler SHALL call `get_engagement_context_by_email` via the MCP_Server.
2. WHEN `get_engagement_context_by_email` returns `status=success`, THE RecommendedVolunteerHandler SHALL set `identity_verified=true` in the Sub_State, cache the Engagement_Context, and advance to the `gathering_preferences` stage.
3. WHEN both phone and email lookups return `not_found`, THE LLM SHALL call `signal_outcome` with `outcome=not_registered`, and THE RecommendedVolunteerHandler SHALL advance the session to the `not_registered` terminal stage.

### Requirement 5: Registration URL Redirect for Unregistered Volunteers

**User Story:** As an unregistered volunteer who was recommended, I want to receive a link to register, so that I can sign up and return to the system afterward.

#### Acceptance Criteria

1. WHEN the session reaches the `not_registered` stage, THE RecommendedVolunteerHandler SHALL include the Registration_URL in the response message.
2. THE Registration_URL SHALL be configurable via the `VOLUNTEER_REGISTRATION_URL` environment variable with a default value of `https://up.serve.net.in`.
3. WHEN the `not_registered` stage is reached, THE RecommendedVolunteerHandler SHALL log the event via `domain_client.log_event()` and treat the stage as terminal.

### Requirement 6: Preference Gathering

**User Story:** As a verified recommended volunteer, I want to share my teaching preferences conversationally, so that the system can find a suitable teaching opportunity for me.

#### Acceptance Criteria

1. WHEN the session is in the `gathering_preferences` stage, THE RecommendedVolunteerHandler SHALL use the LLM to conversationally gather the volunteer's subject preference, school preference, preferred time slot, and availability.
2. WHEN the LLM has gathered sufficient preferences, THE LLM SHALL call `signal_outcome` with `outcome=ready`, `preference_notes`, and `available_from`.
3. WHEN the volunteer indicates they want to defer, THE LLM SHALL call `signal_outcome` with `outcome=deferred` and a reason, and THE RecommendedVolunteerHandler SHALL advance the session to the `paused` stage.
4. WHEN the volunteer declines to proceed, THE LLM SHALL call `signal_outcome` with `outcome=declined`, and THE RecommendedVolunteerHandler SHALL advance the session to the `human_review` stage.

### Requirement 7: Handoff to Fulfillment Agent

**User Story:** As a recommended volunteer who has confirmed preferences, I want to be seamlessly handed off to the matching system, so that I can be assigned a teaching opportunity.

#### Acceptance Criteria

1. WHEN `signal_outcome` with `outcome=ready` is received and `identity_verified=true`, THE RecommendedVolunteerHandler SHALL build a FulfillmentHandoffPayload and emit a handoff event to the Fulfillment_Agent.
2. THE FulfillmentHandoffPayload for recommended volunteers SHALL have `continuity=different`, `preferred_need_id=null`, `preferred_school_id=null`, and `fulfillment_history` as an empty list.
3. THE FulfillmentHandoffPayload SHALL include the `volunteer_id` and `volunteer_name` from the verified Engagement_Context and the `preference_notes` captured during the gathering stage.
4. IF the RecommendedVolunteerHandler cannot construct a valid FulfillmentHandoffPayload (e.g., `volunteer_id` is missing), THEN THE RecommendedVolunteerHandler SHALL advance the session to `human_review` with reason `missing_handoff_context`.

### Requirement 8: Terminal State Handling

**User Story:** As a system operator, I want terminal states to be handled consistently, so that no unnecessary LLM calls are made for completed sessions.

#### Acceptance Criteria

1. WHEN a request arrives for a session in the `not_registered` or `human_review` stage, THE RecommendedVolunteerHandler SHALL return a static fallback message without invoking the LLM.
2. WHEN a request arrives for a session in the `paused` stage, THE RecommendedVolunteerHandler SHALL return a static fallback message without invoking the LLM.

### Requirement 9: Isolation from Existing Engagement Workflow

**User Story:** As a developer, I want the recommended volunteer workflow to be completely isolated from the existing returning volunteer engagement flow, so that no regressions are introduced.

#### Acceptance Criteria

1. THE RecommendedVolunteerHandler SHALL be a separate class that does not import from or modify the existing EngagementAgentService class.
2. WHEN a request has `workflow=returning_volunteer`, THE Engagement_Agent SHALL route it exclusively to the existing EngagementAgentService, and THE RecommendedVolunteerHandler SHALL not be invoked.
3. THE RecommendedVolunteerHandler SHALL reuse the existing MCP_Server tools (`get_engagement_context`, `get_engagement_context_by_email`, `signal_outcome`) via `domain_client` without adding new MCP tools.

### Requirement 10: LLM Loop Safety

**User Story:** As a system operator, I want the LLM tool-calling loop to have bounded iterations, so that runaway loops are prevented and sessions are gracefully escalated.

#### Acceptance Criteria

1. THE RecommendedVolunteerHandler SHALL limit the LLM tool-calling loop to a maximum of 8 iterations per turn.
2. IF the LLM loop exhausts all iterations without producing a text response or a Signal_Outcome, THEN THE RecommendedVolunteerHandler SHALL advance the session to `human_review` with reason `loop_exhausted`.

### Requirement 11: UI Entry Point for Recommended Volunteers

**User Story:** As a recommended volunteer using the web interface, I want a dedicated entry point, so that I can start the recommended volunteer workflow directly.

#### Acceptance Criteria

1. WHEN a user selects the "Recommended Volunteer" role from the role selector, THE UI SHALL navigate to a dedicated RecommendedVolunteerView.
2. THE RecommendedVolunteerView SHALL send the initial request with `persona=recommended_volunteer` to the Orchestrator.
3. THE RecommendedVolunteerView SHALL not require a phone number upfront — the agent asks for it during the conversation.

### Requirement 12: Error Handling for MCP Unavailability

**User Story:** As a recommended volunteer, I want the system to handle backend failures gracefully, so that I receive a helpful response even when services are down.

#### Acceptance Criteria

1. IF `get_engagement_context` or `get_engagement_context_by_email` raises an exception or returns `status=error`, THEN THE RecommendedVolunteerHandler SHALL continue the conversation without exposing the error to the volunteer.
2. IF identity cannot be verified after all lookup attempts due to errors, THEN THE RecommendedVolunteerHandler SHALL advance the session to `human_review` with an appropriate reason.
