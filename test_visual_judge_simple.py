
import sys
import os
from visual_judge import VisualJudge

def test_visual_judge():
    judge = VisualJudge()
    print(f"Gemini available: {judge.gemini_client is not None}")
    print(f"Qwen available: {judge.qwen_client is not None}")
    
    # Check if we have any test images
    test_images = ["test_30分钟_chart.png", "test_5分钟_chart.png"]
    existing_images = [img for img in test_images if os.path.exists(img)]
    
    if not existing_images:
        print("No test images found to run a real evaluation.")
        return

    print(f"Running evaluation with: {existing_images}")
    result = judge.evaluate(existing_images, signal_type="b2")
    print("\nFinal Result:")
    import json
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    test_visual_judge()
