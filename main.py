import os
import tkinter as tk
from dotenv import load_dotenv

load_dotenv()

from ui.dashboard import VisaAppGUI

def main():
    if not os.environ.get("GEMINI_API_KEY"):
        print("WARNING: GEMINI_API_KEY not found in .env file.")
    
    # Initialize and launch the dashboard
    root = tk.Tk()
    app = VisaAppGUI(root)
    root.mainloop()
    

if __name__ == "__main__":
    main()