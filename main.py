#!/usr/bin/env python3
"""
Galactic Conclave — AI Empire Chat Overlay v0.6.0
====================================================
The central entry point for the application. 
Handles dependency checks, logging initialization, and UI launch.
"""

import sys
import tkinter as tk
from tkinter import messagebox

def _check_dependencies():
    """Verify required packages are installed before the UI starts."""
    missing = []
    # Core LLM and Automation requirements
    try:
        import openai 
    except ImportError:
        missing.append("openai")
    try:
        import pyautogui 
    except ImportError:
        missing.append("pyautogui")
    try:
        import pygetwindow 
    except ImportError:
        missing.append("pygetwindow")
        
    # Anthropic is optional but recommended
    try:
        import anthropic 
    except ImportError:
        print("WARNING: 'anthropic' not installed. Claude provider unavailable.", file=sys.stderr)

    if missing:
        # Create a hidden root just to show the error box
        _root = tk.Tk()
        _root.withdraw()
        messagebox.showerror(
            "Missing Dependencies", 
            f"The following required packages are missing:\n\n"
            f"pip install {' '.join(missing)}\n\n"
            "Please install them and restart the application."
        )
        sys.exit(1)

def main():
    # 1. Safety check
    _check_dependencies()

    # 2. Initialize Logging (v0.6)
    from config import setup_logging
    logger = setup_logging()
    
    logger.info("=" * 50)
    logger.info("Galactic Conclave v0.6.0 starting...")
    logger.info("=" * 50)

    # 3. Launch UI
    root = tk.Tk()
    from ui import GalacticConclave
    
    try:
        # Pass the root to the main UI class
        GalacticConclave(root)
        root.mainloop()
    except Exception as e:
        logger.exception("Fatal error in main loop:")
        # Show error to user before crashing
        messagebox.showerror("Fatal Error", f"The application encountered an error:\n\n{e}")
        raise
    finally:
        logger.info("Galactic Conclave session closed.")

if __name__ == "__main__":
    main()