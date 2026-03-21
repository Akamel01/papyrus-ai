import sys
sys.path.insert(0, r"c:\gpt\SME")
from src.utils.question_classifier import get_paper_range

query = """You are an expert research synthesis and proposal-writing agent specializing in:
•	Conflict-based road safety assessment
•	Traffic safety analytics
•	Bayesian hierarchical modeling
•	Extreme Value Theory (EVT)
•	Spatial statistics
•	Spatio-temporal modeling
•	Hierarchical dependence structures
•	Transportation safety management systems
Retrieve the following documents and include them in the proposal:
Title: The tail process and tail measure of continuous time regularly varying stochastic processes with doi:10.1007/s10687-021-00417-3
The proposed conceptual modeling framework should rightfully argue that it should achieve the research objectives and cover critical gaps in the literature.
The research objectives and expected scientific contributions are the most important sections. 
REQUIRED """

result = get_paper_range(query, depth="High", auto_decide=True)
print(f"Result paper range: {result}")
