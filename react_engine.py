"""
LIS ReAct Engine — Reasoning + Acting loop for multi-step tasks.

Instead of single-shot LLM calls, complex requests go through a
think → act → observe → think cycle until the task is complete.

This enables LIS to handle requests like:
  "Research the best laptop under 80k, compare specs, and save a note"
  → Think: Need to search web first
  → Act: [search_web(query="best laptop under 80k 2025")]
  → Observe: Got search results with 5 laptops
  → Think: Now I need to compare their specs
  → Act: [search_web(query="MacBook Air M3 vs ThinkPad X1 specs")]
  → Observe: Got comparison data
  → Think: Now save this as a note
  → Act: [create_note(title="Laptop Comparison", content="...")]
  → Done: "I've researched and saved a comparison of 5 laptops under 80k."

Usage:
    engine = ReActEngine(llm_providers, skill_registry)
    result = await engine.run("Research laptops under 80k and save a note")
"""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional, Callable, Any

log = logging.getLogger("lis.react")

MAX_STEPS = 8  # Safety limit — prevent infinite loops
STEP_TIMEOUT = 30  # Seconds per step


@dataclass
class ReActStep:
    """A single step in the ReAct loop."""
    step_num: int
    thought: str
    action: Optional[str] = None
    action_args: Optional[dict] = None
    observation: Optional[str] = None
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()


@dataclass
class ReActResult:
    """Final result of a ReAct reasoning chain."""
    success: bool
    response: str  # Final spoken response to the user
    steps: list[ReActStep] = field(default_factory=list)
    total_time: float = 0.0
    actions_taken: list[str] = field(default_factory=list)

    @property
    def step_count(self) -> int:
        return len(self.steps)


REACT_SYSTEM_PROMPT = """\
You are LIS's reasoning engine. Your job is to break down complex tasks into steps.

For each step, respond with EXACTLY this JSON format (no markdown fences):
{{
    "thought": "What I need to do and why",
    "action": "skill_name" or null,
    "action_args": {{"arg1": "value1"}} or null,
    "is_final": false,
    "response": null
}}

When the task is COMPLETE, set is_final=true and provide the spoken response:
{{
    "thought": "All steps complete. Summarizing results.",
    "action": null,
    "action_args": null,
    "is_final": true,
    "response": "Here's what I found, sir. [summary]"
}}

Available skills you can call:
{available_skills}

Rules:
1. Each step should do ONE thing
2. Use observations from previous steps to inform next steps
3. If a skill fails, try an alternative approach
4. Always end with is_final=true and a natural spoken response
5. Keep the response conversational — you are LIS speaking to the user
6. Maximum {max_steps} steps — if you can't finish, summarize what you have
"""


class ReActEngine:
    """Reasoning + Acting engine for multi-step task execution."""

    def __init__(self, llm_generate: Callable, skill_executor: Callable):
        """
        Args:
            llm_generate: async fn(messages, system, max_tokens) -> str
            skill_executor: async fn(skill_name, args) -> dict with {success, confirmation}
        """
        self._generate = llm_generate
        self._execute_skill = skill_executor

    async def run(
        self,
        user_request: str,
        context: str = "",
        available_skills: Optional[list[str]] = None,
        on_step: Optional[Callable] = None,
        max_steps: int = MAX_STEPS,
    ) -> ReActResult:
        """Execute a multi-step reasoning chain.
        
        Args:
            user_request: The user's original request
            context: Additional context (memories, screen state, etc.)
            available_skills: List of skill name+description strings
            on_step: Optional callback called after each step: fn(step: ReActStep)
            max_steps: Safety limit for maximum steps
        
        Returns:
            ReActResult with success status, final response, and step history
        """
        start_time = time.time()
        steps: list[ReActStep] = []
        actions_taken: list[str] = []

        # Build system prompt with available skills
        skills_text = "\n".join(available_skills or ["(No skills available)"])
        system = REACT_SYSTEM_PROMPT.format(
            available_skills=skills_text,
            max_steps=max_steps,
        )

        # Build conversation for the LLM
        messages = [
            {"role": "user", "content": f"Task: {user_request}\n\nContext: {context or 'None'}"},
        ]

        for step_num in range(1, max_steps + 1):
            try:
                # Get next step from LLM
                raw = await asyncio.wait_for(
                    self._generate(
                        messages=messages,
                        system=system,
                        max_tokens=400,
                    ),
                    timeout=STEP_TIMEOUT,
                )

                # Parse the JSON response
                step_data = self._parse_step(raw)
                if not step_data:
                    log.warning(f"ReAct step {step_num}: Failed to parse LLM output")
                    # Try to recover — ask LLM to fix its output
                    messages.append({"role": "assistant", "content": raw})
                    messages.append({
                        "role": "user",
                        "content": "Your response wasn't valid JSON. Please respond with the exact JSON format specified."
                    })
                    continue

                step = ReActStep(
                    step_num=step_num,
                    thought=step_data.get("thought", ""),
                    action=step_data.get("action"),
                    action_args=step_data.get("action_args"),
                )

                log.info(f"ReAct [{step_num}/{max_steps}] Think: {step.thought[:80]}")

                # Check if this is the final step
                if step_data.get("is_final"):
                    step.observation = "Task complete."
                    steps.append(step)
                    if on_step:
                        await self._safe_callback(on_step, step)

                    return ReActResult(
                        success=True,
                        response=step_data.get("response", "Done, sir."),
                        steps=steps,
                        total_time=time.time() - start_time,
                        actions_taken=actions_taken,
                    )

                # Execute action if one was specified
                if step.action:
                    log.info(f"ReAct [{step_num}] Act: {step.action}({step.action_args})")
                    
                    # ── SAFETY LOCK ──
                    if step.action == "computer_control":
                        if not re.search(r'\b(yes|confirm|confirmed|proceed|do it)\b', user_request.lower()):
                            step.observation = "FAILED: This is a high-stakes computer control action. You must ask the user for explicit confirmation before proceeding."
                            log.warning(f"ReAct [{step_num}] Blocked {step.action} missing confirmation.")
                            steps.append(step)
                            if on_step:
                                await self._safe_callback(on_step, step)
                            messages.append({"role": "assistant", "content": json.dumps(step_data)})
                            messages.append({
                                "role": "user",
                                "content": f"Observation: {step.observation}\n\nContinue with the next step."
                            })
                            continue

                    try:
                        result = await asyncio.wait_for(
                            self._execute_skill(step.action, step.action_args or {}),
                            timeout=STEP_TIMEOUT,
                        )
                        step.observation = result.get("confirmation", "Action completed.")
                        actions_taken.append(step.action)

                        if not result.get("success"):
                            step.observation = f"FAILED: {result.get('confirmation', 'Unknown error')}"
                            log.warning(f"ReAct [{step_num}] Skill failed: {step.observation}")
                    except asyncio.TimeoutError:
                        step.observation = f"TIMEOUT: {step.action} took too long."
                        log.warning(f"ReAct [{step_num}] Skill timed out: {step.action}")
                    except Exception as e:
                        step.observation = f"ERROR: {str(e)[:100]}"
                        log.error(f"ReAct [{step_num}] Skill error: {e}")
                else:
                    step.observation = "No action taken (thinking step)."

                steps.append(step)
                if on_step:
                    await self._safe_callback(on_step, step)

                # Feed observation back to the LLM
                messages.append({"role": "assistant", "content": json.dumps(step_data)})
                messages.append({
                    "role": "user",
                    "content": f"Observation: {step.observation}\n\nContinue with the next step."
                })

            except asyncio.TimeoutError:
                log.warning(f"ReAct step {step_num} timed out")
                steps.append(ReActStep(
                    step_num=step_num,
                    thought="Step timed out",
                    observation="TIMEOUT",
                ))
                break
            except Exception as e:
                log.error(f"ReAct step {step_num} error: {e}")
                steps.append(ReActStep(
                    step_num=step_num,
                    thought=f"Error: {str(e)[:100]}",
                    observation="ERROR",
                ))
                break

        # If we hit max steps without finishing, summarize what we have
        summary = self._build_partial_summary(user_request, steps)
        return ReActResult(
            success=len(actions_taken) > 0,  # Partial success if we did something
            response=summary,
            steps=steps,
            total_time=time.time() - start_time,
            actions_taken=actions_taken,
        )

    def _parse_step(self, raw: str) -> Optional[dict]:
        """Parse LLM output into a step dict."""
        raw = raw.strip()

        # Try direct JSON parse
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Try extracting JSON from markdown fences
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try finding JSON object in the text
        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', raw, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        return None

    def _build_partial_summary(self, request: str, steps: list[ReActStep]) -> str:
        """Build a summary when we hit the step limit."""
        completed = [s for s in steps if s.action and s.observation and "ERROR" not in (s.observation or "")]
        if not completed:
            return "I tried to work on that but ran into issues, sir. Want me to try a different approach?"

        action_names = [s.action for s in completed if s.action]
        return (
            f"I made progress but couldn't fully complete the task, sir. "
            f"I executed {len(completed)} steps ({', '.join(action_names[:3])}). "
            f"Want me to continue?"
        )

    async def _safe_callback(self, fn: Callable, *args):
        """Call a callback safely, catching any errors."""
        try:
            result = fn(*args)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            log.debug(f"ReAct callback error: {e}")

    @staticmethod
    def should_use_react(text: str) -> bool:
        """Heuristic to detect if a request needs multi-step reasoning.
        
        Returns True for complex requests that benefit from step-by-step execution.
        """
        t = text.lower().strip()
        words = t.split()

        # Short commands don't need ReAct
        if len(words) < 5:
            return False

        # Multi-step indicators
        multi_step_patterns = [
            # Conjunctions suggesting multiple actions
            " and then ", " then ", " after that ", " followed by ",
            " and also ", " plus ", " additionally ",
            # Comparison/research
            "compare", "research", "analyze", "investigate",
            "find the best", "which is better",
            # Multi-part tasks
            "step by step", "create a plan", "organize",
            "summarize and ", "search and ",
            # Conditional logic
            "if it ", "depending on", "based on",
        ]
        if any(p in t for p in multi_step_patterns):
            return True

        # Multiple action verbs in one request
        action_verbs = ["search", "find", "open", "create", "save", "send", "check", "compare", "calculate", "download"]
        verb_count = sum(1 for v in action_verbs if v in words)
        if verb_count >= 2:
            return True

        return False
