import os
from pathlib import Path
from typing import List
from langchain.tools import tool

SKILLS_DIR = Path("src/skills")

@tool
def load_skills(skill_names: List[str]) -> str:
    """
    Dynamically loads domain business rules and instructions for one or more specific analysis tasks.

    Args:
        skill_names (list[str]): List of skill domain identifiers to load.
            Available options:
            - 'database_schema_context': Schema rules, mandatory LIMIT, performance constraints.
            - 'data_quality_grading': Criteria for Grade A through Grade F, 6 core identity fields.
            - 'sync_and_link_tracker': Batch synchronization status & verbatim preview/investigate link rules.
            - 'mismatch_reasoning': Protocols for investigating records in MANUAL_REVIEW or AUTO_UNMATCH.

    Returns:
        str: The combined full-text guidelines for the requested domain skills.
    """
    if not isinstance(skill_names, list) or not skill_names:
        return "Error: skill_names must be a non-empty list of skill names."

    loaded = []
    for name in skill_names:
        clean = name.strip()
        skill_file = SKILLS_DIR / clean / "SKILL.md"
        if skill_file.exists():
            with open(skill_file, "r", encoding="utf-8") as f:
                loaded.append(f"=== SKILL: {clean} ===\n" + f.read().strip())
        else:
            loaded.append(
                f"=== SKILL ERROR: {clean} ===\nSkill '{clean}' not found. "
                "Available skills: 'database_schema_context', 'data_quality_grading', "
                "'sync_and_link_tracker', 'mismatch_reasoning'."
            )
    return "\n\n".join(loaded)
