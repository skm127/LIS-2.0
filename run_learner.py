"""
Standalone trigger script for the LIS Autonomous Learner.
Run this script to manually test topic extraction and web ingestion.

Usage:
    python run_learner.py "I am building a web app using FastAPI and React"
"""

import sys
import asyncio
import logging
from autonomous_learner import run_learning_cycle

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

def main():
    print("Starting LIS Autonomous Learner (Standalone Mode)")
    
    # Check if user provided recent activity text
    if len(sys.argv) > 1:
        activity = " ".join(sys.argv[1:])
    else:
        print("No activity provided. Using default test activity.")
        activity = "I am debugging an issue with React hooks, specifically useEffect."
        
    print(f"\n[Activity to analyze]: {activity}\n")
    
    # We must explicitly enable it here for testing, even if it's off in .env
    import os
    os.environ["ENABLE_AUTONOMOUS_LEARNING"] = "True"
    
    try:
        asyncio.run(run_learning_cycle(activity))
        print("\nLearning cycle completed successfully.")
    except KeyboardInterrupt:
        print("\n\nLearning cycle interrupted by user.")
    except Exception as e:
        print(f"\nLearning cycle failed: {e}")

if __name__ == "__main__":
    main()
