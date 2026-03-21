
from src.utils.adaptive_tokens import AdaptiveTokenManager

def test_limits():
    manager = AdaptiveTokenManager(depth="High")
    
    # 1. Intro (Low citations)
    lim_intro = manager.get_section_limits(0, 3)
    print(f"Intro (3 cit): {lim_intro['max_output_tokens']}")
    
    # 2. Main Body (Med citations)
    lim_body = manager.get_section_limits(1, 8)
    print(f"Body (8 cit): {lim_body['max_output_tokens']}")
    
    # 3. Comparative (High citations)
    lim_comp = manager.get_section_limits(2, 15)
    print(f"Comparative (15 cit): {lim_comp['max_output_tokens']}")

if __name__ == "__main__":
    test_limits()
