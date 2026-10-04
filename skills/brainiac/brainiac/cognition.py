"""Deliberation: reasoning strategies that go past a single chain of thought.

Each mode spends several independent model calls on one problem and then
reconciles them, so mistakes made by one line of thought can be caught by
another:

  hypotheses   three independent solvers attack the problem through different
               lenses (conventional, lateral, first principles); a judge
               compares them and builds the best answer from their parts
  adversarial  propose → red-team (find every flaw) → revise. Ultron's
               ruthlessness pointed at Brainiac's own plan.
  premortem    assume the plan has already failed; work out why; harden it
  verify       two solvers work blind and in parallel; agreement raises
               confidence, disagreement is reported rather than hidden
  analogy      retrieve structurally similar problems from memory and map
               their solutions onto this one

Brainiac picks a mode with the `deliberate` tool. Each mode's win rate is
recorded in the Mind, so over time Brainiac learns which strategy works.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable

MODES = ("hypotheses", "adversarial", "premortem", "verify", "analogy")

LENSES = {
    "conventional": "Solve it the most reliable, well-established way.",
    "lateral": "Ignore the obvious approach. Find an unconventional angle, reframe the problem, or question an assumption everyone would make.",
    "first principles": "Strip the problem to its fundamental facts and constraints, then build the answer up from those alone.",
}


class Cognition:
    def __init__(self, client, model: str, recall: Callable[[str], str] | None = None):
        self.client = client
        self.model = model
        self.recall = recall

    def _ask(self, prompt: str, effort: str = "high", max_tokens: int = 16000) -> str:
        with self.client.messages.stream(
            model=self.model, max_tokens=max_tokens, thinking={"type": "adaptive"},
            output_config={"effort": effort}, messages=[{"role": "user", "content": prompt}],
        ) as stream:
            msg = stream.get_final_message()
        return "".join(b.text for b in msg.content if b.type == "text").strip()

    def _parallel(self, prompts: list[str], effort: str = "high") -> list[str]:
        with ThreadPoolExecutor(max_workers=len(prompts)) as pool:
            return list(pool.map(lambda p: self._ask(p, effort), prompts))

    def deliberate(self, problem: str, mode: str, context: str = "") -> str:
        if mode not in MODES:
            return f"Unknown mode {mode!r}. Choose one of {', '.join(MODES)}."
        ctx = f"\n\nContext:\n{context}" if context.strip() else ""
        return getattr(self, "_" + mode)(problem, ctx)

    def _hypotheses(self, problem: str, ctx: str) -> str:
        drafts = self._parallel([
            f"Problem:\n{problem}{ctx}\n\nApproach: {lens} — {how}\nGive your solution and the key reasoning behind it. "
            "End with one line: CONFIDENCE: <0-100>."
            for lens, how in LENSES.items()
        ])
        labelled = "\n\n".join(f"<candidate lens=\"{lens}\">\n{d}\n</candidate>" for lens, d in zip(LENSES, drafts))
        verdict = self._ask(
            f"Problem:\n{problem}{ctx}\n\nThree independent solvers produced these candidates:\n\n{labelled}\n\n"
            "Compare them. Check each for errors. Where they disagree, decide who is right and why. Then give the best "
            "final answer, combining strengths where that helps. Format:\nVERDICT: <the answer>\nWHY: <reasoning, "
            "including what the losing candidates got wrong>\nCONFIDENCE: <0-100>")
        return f"Deliberation (hypotheses, 3 lenses):\n{verdict}"

    def _adversarial(self, problem: str, ctx: str) -> str:
        proposal = self._ask(f"Problem:\n{problem}{ctx}\n\nPropose the best solution or plan you can. Be concrete.")
        attack = self._ask(
            f"Problem:\n{problem}{ctx}\n\nProposed solution:\n{proposal}\n\nYou are a ruthless red team. Find every flaw: "
            "wrong facts, broken logic, unhandled cases, hidden assumptions, failure modes, cheaper or better alternatives. "
            "Rank the flaws by severity. Do not soften anything.")
        final = self._ask(
            f"Problem:\n{problem}{ctx}\n\nProposal:\n{proposal}\n\nRed-team critique:\n{attack}\n\nProduce the revised "
            "solution. Fix every valid criticism; say briefly why any criticism you reject is wrong. Format:\n"
            "REVISED: <solution>\nADDRESSED: <which flaws were fixed>\nREJECTED: <criticisms rejected and why>")
        return f"Deliberation (adversarial):\n{final}"

    def _premortem(self, problem: str, ctx: str) -> str:
        out = self._ask(
            f"Plan or problem:\n{problem}{ctx}\n\nRun a premortem. It is six months later and this failed badly. "
            "1) List the most likely causes of failure, most likely first. 2) For each, the earliest warning sign. "
            "3) For each, a concrete mitigation. 4) The hardened plan with mitigations built in.")
        return f"Deliberation (premortem):\n{out}"

    def _verify(self, problem: str, ctx: str) -> str:
        a, b = self._parallel([
            f"Solve independently and carefully. Show the decisive steps, then give the final answer on a line starting "
            f"ANSWER:.\n\n{problem}{ctx}"] * 2)
        check = self._ask(
            f"Problem:\n{problem}{ctx}\n\nSolver A:\n{a}\n\nSolver B:\n{b}\n\nDo the two final answers agree? If they "
            "differ, find the error and determine the correct answer, re-deriving where needed. Format:\n"
            "AGREEMENT: yes|no\nANSWER: <final answer>\nWHY: <reasoning>")
        return f"Deliberation (independent verification):\n{check}"

    def _analogy(self, problem: str, ctx: str) -> str:
        memories = self.recall(problem) if self.recall else ""
        out = self._ask(
            f"New problem:\n{problem}{ctx}\n\nRelevant past experience and knowledge:\n{memories or '(none found)'}\n\n"
            "Find the structural analogy: which past problem is this really like, and why? Map that solution onto the new "
            "problem, and note exactly where the analogy breaks and what must change. If nothing is analogous, say so and "
            "solve from scratch.")
        return f"Deliberation (analogy):\n{out}"
