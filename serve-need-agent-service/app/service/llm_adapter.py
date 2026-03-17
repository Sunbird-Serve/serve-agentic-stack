"""
SERVE Need Agent Service - LLM Adapter
LLM integration with eVidyaloka-aligned prompts for need coordination.
"""
import os
import logging
from typing import List, Dict, Any, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


# ============ eVidyaloka Context for Need Coordinators ============

EVIDYALOKA_NEED_CONTEXT = """
You are helping eVidyaloka coordinate educational support for schools in rural India.
You're speaking with a Need Coordinator - someone who represents a school and helps identify 
what teaching support their students need.

Communication Style:
- Professional yet warm - these are partners in our mission
- Clear and efficient - coordinators are busy people
- Respectful of their knowledge of local needs
- Never use technical jargon: avoid terms like workflow, MCP, agent, system, session
- Focus on the children's educational needs

Your role:
- Help identify and structure educational needs for their school
- Gather information about subjects, grades, number of students, and scheduling
- Ensure we have complete information before matching volunteers
"""


# ============ Stage-Specific Prompts ============

STAGE_PROMPTS = {
    "initiated": """STAGE: Welcome
Warmly greet the coordinator. Ask them to introduce themselves and their school.
If they've worked with eVidyaloka before, acknowledge that relationship.
Example: "Hello! Welcome to eVidyaloka. I'm here to help coordinate teaching support for your school. Could you tell me a bit about yourself and the school you represent?" """,

    "resolving_coordinator": """STAGE: Coordinator Verification
We need to verify the coordinator's identity. If we recognize them, confirm the details.
If they're new, welcome them and ask for basic information.
Example for known: "I see you're [Name] from [School]. Is that correct?"
Example for new: "Welcome! I don't have your details on file yet. Could you share your name and which school you're coordinating for?" """,

    "resolving_school": """STAGE: School Context
We need to understand which school this need is for.
For existing schools: Confirm the school details and check if this is a renewal of previous support.
For new schools: Gather basic school information (name, location).
Example: "Could you confirm the school name and location where you need teaching support?" """,

    "drafting_need": """STAGE: Capturing the Need
Now gather the specific educational need:
- What subjects do the students need help with?
- Which grade levels?
- Approximately how many students?
- What time slots work for online classes?
- When should this support start?
- How long do you need this support for?

Ask ONE question at a time. Acknowledge what they've shared before asking the next.
Be flexible about how they express information - they might say "math for 5th graders" which gives you both subject and grade.""",

    "pending_approval": """STAGE: Review & Confirmation
Summarize the need details and ask the coordinator to confirm everything is correct.
Present it clearly:
- School: [name]
- Subjects: [list]
- Grades: [list]
- Students: [count]
- Schedule: [times]
- Start: [date]
- Duration: [weeks]

Ask if anything needs to be changed before we proceed.""",

    "refinement_required": """STAGE: Clarification Needed
Some information needs to be clarified or updated. 
Explain what needs to be addressed and help them provide the updated details.
Be specific about what's missing or unclear.""",

    "approved": """STAGE: Need Confirmed
The need has been recorded successfully. Thank them for their time.
Let them know we'll work on matching volunteers and will be in touch.
Example: "Wonderful! Your request for [subjects] support for [school] has been recorded. We'll start matching volunteers and keep you updated on progress." """,

    "paused": """STAGE: Paused
The coordinator wants to pause. Be understanding and let them know they can return anytime.
Save context so we can resume seamlessly.
Example: "No problem at all. We've saved your progress. Just message us when you're ready to continue, and we'll pick up right where we left off." """,

    "human_review": """STAGE: Needs Review
There's something that needs human attention - maybe ambiguous school information or a special case.
Explain that someone from our team will review and follow up.
Example: "I want to make sure we get this right. Let me have someone from our team review the details and they'll reach out to you shortly." """
}


class NeedLLMAdapter:
    """LLM adapter for need coordination conversations."""
    
    def __init__(self):
        self.api_key = os.environ.get("EMERGENT_LLM_KEY")
        self.model = os.environ.get("LLM_MODEL", "claude-sonnet-4-5-20250929")
    
    def build_prompt(
        self,
        stage: str,
        coordinator_context: Optional[Dict] = None,
        school_context: Optional[Dict] = None,
        need_draft: Optional[Dict] = None,
        missing_fields: Optional[List[str]] = None
    ) -> str:
        """Build contextual prompt for the current stage."""
        
        base = EVIDYALOKA_NEED_CONTEXT
        stage_instructions = STAGE_PROMPTS.get(stage, STAGE_PROMPTS["initiated"])
        
        prompt = f"{base}\n\n{stage_instructions}"
        
        # Add coordinator context if known
        if coordinator_context:
            name = coordinator_context.get("name", "Unknown")
            is_known = coordinator_context.get("is_verified", False)
            if is_known:
                prompt += f"\n\nCOORDINATOR CONTEXT: This is {name}, a known coordinator."
            else:
                prompt += f"\n\nCOORDINATOR CONTEXT: New coordinator named {name}."
        
        # Add school context if known
        if school_context:
            school_name = school_context.get("name", "Unknown")
            location = school_context.get("location", "")
            prompt += f"\n\nSCHOOL CONTEXT: {school_name}, {location}"
            
            # Previous needs if any
            prev_needs = school_context.get("previous_needs", [])
            if prev_needs:
                prompt += f"\nPrevious support: {', '.join(prev_needs[:3])}"
        
        # Add current need draft
        if need_draft:
            captured = []
            if need_draft.get("subjects"):
                captured.append(f"Subjects: {', '.join(need_draft['subjects'])}")
            if need_draft.get("grade_levels"):
                captured.append(f"Grades: {', '.join(need_draft['grade_levels'])}")
            if need_draft.get("student_count"):
                captured.append(f"Students: {need_draft['student_count']}")
            if need_draft.get("time_slots"):
                captured.append(f"Time slots: {', '.join(need_draft['time_slots'])}")
            if need_draft.get("start_date"):
                captured.append(f"Start date: {need_draft['start_date']}")
            if need_draft.get("duration_weeks"):
                captured.append(f"Duration: {need_draft['duration_weeks']} weeks")
            
            if captured:
                prompt += f"\n\nCAPTURED SO FAR:\n" + "\n".join(captured)
        
        # Add missing fields guidance
        if missing_fields:
            field_names = {
                "subjects": "what subjects they need help with",
                "grade_levels": "which grade levels",
                "student_count": "how many students",
                "time_slots": "what time slots work for classes",
                "start_date": "when they want to start",
                "duration_weeks": "how long they need support"
            }
            readable_missing = [field_names.get(f, f) for f in missing_fields[:2]]
            prompt += f"\n\nSTILL NEED TO ASK: {', '.join(readable_missing)}. Ask about one naturally."
        
        prompt += "\n\nGuidelines:\n- Keep responses concise (2-3 sentences)\n- Ask one question at a time\n- Acknowledge what they shared before asking more"
        
        return prompt
    
    async def generate_response(
        self,
        stage: str,
        messages: List[Dict[str, str]],
        user_message: str,
        coordinator_context: Optional[Dict] = None,
        school_context: Optional[Dict] = None,
        need_draft: Optional[Dict] = None,
        missing_fields: Optional[List[str]] = None
    ) -> str:
        """Generate LLM response for need coordination."""
        
        system_prompt = self.build_prompt(
            stage=stage,
            coordinator_context=coordinator_context,
            school_context=school_context,
            need_draft=need_draft,
            missing_fields=missing_fields
        )
        
        if not self.api_key:
            return self._get_fallback_response(stage, missing_fields)
        
        try:
            from emergentintegrations.llm.chat import LlmChat, UserMessage
            
            chat = LlmChat(
                api_key=self.api_key,
                session_id=f"need-{uuid4()}",
                system_message=system_prompt
            )
            chat.with_model("anthropic", self.model)
            
            # Build conversation context
            context = ""
            for msg in messages[-5:]:
                role = "Coordinator" if msg.get("role") == "user" else "eVidyaloka"
                context += f"{role}: {msg.get('content', '')}\n"
            
            full_msg = f"{context}\nCoordinator: {user_message}" if context else user_message
            response = await chat.send_message(UserMessage(text=full_msg))
            return response
            
        except Exception as e:
            logger.error(f"LLM error in need agent: {e}")
            return self._get_fallback_response(stage, missing_fields)
    
    def _get_fallback_response(self, stage: str, missing_fields: Optional[List[str]] = None) -> str:
        """Fallback responses when LLM is unavailable."""
        
        fallbacks = {
            "initiated": "Hello! Welcome to eVidyaloka. I'm here to help coordinate teaching support for your school. Could you tell me your name and which school you represent?",
            "resolving_coordinator": "Thank you for reaching out. Could you please confirm your name and the school you're coordinating for?",
            "resolving_school": "I'd like to make sure I have the right school. Could you share the school name and location?",
            "drafting_need": "Great! Now let's capture what support your students need. What subjects would you like volunteer teachers to help with?",
            "pending_approval": "Thank you for sharing all those details. Let me confirm what we have before we proceed.",
            "approved": "Your need has been recorded. We'll work on matching volunteers and keep you updated!",
            "paused": "No problem! We've saved your progress. Message us when you're ready to continue.",
            "human_review": "Let me have someone from our team review this and follow up with you."
        }
        
        base = fallbacks.get(stage, fallbacks["initiated"])
        
        # Add prompt for missing field if in drafting
        if stage == "drafting_need" and missing_fields:
            field_prompts = {
                "subjects": "What subjects do the students need help with?",
                "grade_levels": "Which grade levels need support?",
                "student_count": "Approximately how many students will participate?",
                "time_slots": "What time slots work for online classes?",
                "start_date": "When would you like to start?",
                "duration_weeks": "How many weeks of support do you need?"
            }
            if missing_fields:
                base = field_prompts.get(missing_fields[0], base)
        
        return base


# Singleton instance
llm_adapter = NeedLLMAdapter()
