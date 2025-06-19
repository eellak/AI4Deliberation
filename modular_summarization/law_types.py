"""Type definitions for legislative summarization components.

Contains TypedDict and other type definitions to support
strict typing for narrative planning and synthesis.
"""
from __future__ import annotations

from typing import Dict, List, Optional, TypedDict, Union


class StoryBeat(TypedDict):
    """Represents one narrative unit within a larger narrative plan.
    
    Attributes:
        section_title: Descriptive title for this section of the narrative
        section_role: Function or purpose of this section in the overall narrative  
        source_chapters: List of indices (positions) in the chapter_summaries that are sources for this beat
    """
    section_title: str
    section_role: str
    source_chapters: List[int]


class NarrativePlan(TypedDict):
    """Complete narrative plan for a Part's summarization.
    
    Attributes:
        overall_narrative_arc: One sentence summarizing the overall narrative arc
        protagonist: The main entity/institution affected by this Part
        problem: The problem this Part of the law attempts to solve
        narrative_sections: List of narrative units (StoryBeat) that make up the plan
    """
    overall_narrative_arc: str
    protagonist: str
    problem: str
    narrative_sections: List[StoryBeat]


class GeneratedParagraph(TypedDict):
    """A single paragraph generated for one story beat.
    
    Attributes:
        paragraph: The actual text content of the paragraph
    """
    paragraph: str


# Additional helper types that may be used in the implementation
PlanningInput = Dict[str, Union[List[str], str]]
SynthesisInput = Dict[str, Union[NarrativePlan, List[str], str, int]]
