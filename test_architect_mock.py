import sys
import logging
from pathlib import Path
from dataclasses import dataclass

sys.path.append(str(Path(__file__).parent))

from src.academic_v2.architect import Architect
from src.generation.ollama_client import OllamaClient

@dataclass
class MockType:
    value: str

@dataclass
class MockMethodology:
    type: MockType

@dataclass
class AtomicFact:
    claim_text: str
    id: str
    source_paper_title: str
    year: int
    methodology: MockMethodology

logging.basicConfig(level=logging.ERROR)

facts_text = [
    "Traffic conflicts are valid surrogate safety measures.",
    "Bayesian hierarchical models account for unobserved heterogeneity.",
    "Crash-based analysis suffers from rare event bias.",
    "Extreme value theory (EVT) provides theoretical linkage between conflicts and crashes.",
    "Video-based trajectory extraction allows for high-granularity spatial analysis.",
    "Spatial-temporal correlation is significant in urban networks.",
    "The Peaks-Over-Threshold (POT) method relies on accurately choosing a threshold.",
    "Simulation-based surrogate measures often differ from empirical observations.",
    "Traffic flow variables (volume, speed) directly impact conflict rates.",
    "Pedestrian-vehicle interactions require distinct severity indicators.",
    "Empirical Bayes relies on reference populations, while Hierarchical Bayes does not.",
    "Posterior predictive checks are critical for model validation."
]

facts = [
    AtomicFact(
        claim_text=f"{facts_text[i % len(facts_text)]} (Extra variable {i})", 
        id=f"fact_{i}", 
        source_paper_title=f"Paper Title {i}",
        year=2015 + (i % 10),
        methodology=MockMethodology(type=MockType(value="Quantitative"))
    )
    for i in range(1, 35)
]

llm = OllamaClient(model_name="gpt-oss:120b-cloud")
architect = Architect(llm_client=llm)

plan = architect.design_section_plan(
    query="Theoretical Foundations of Conflict-Based Safety Models",
    section_name="Methodological Taxonomy of Bayesian Approaches",
    facts=facts,
    review_text="This review explores bayesian methods for conflict modeling."
)

print(f"\nFinal Plan returned:\n{plan}")
