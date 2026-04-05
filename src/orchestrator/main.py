import tkinter as tk


def main():
    root = tk.Tk()
    root.title("ClaudeCode Orchestrator")
    root.geometry("800x600")

    label = tk.Label(root, text="ClaudeCode Orchestrator", font=("Segoe UI", 20))
    label.pack(expand=True)

    root.mainloop()


if __name__ == "__main__":
    main()
