import customtkinter as ctk
import sys

class NovaApp(ctk.CTk):
    def __init__(self, pipeline=None, **kwargs):
        super().__init__(**kwargs)
        self.pipeline = pipeline  # This catches the backend logic!

        # --- Window Setup ---
        self.title("Nova Voice Assistant")
        self.geometry("900x600")
        
        # Premium Touch: Slight transparency for that glass effect (0.0 to 1.0)
        self.attributes("-alpha", 0.97) 
        
        # Force dark mode and set a sleek global color theme
        ctk.set_appearance_mode("dark")
        # We use a custom dark palette instead of the default blue/green/purple
        self.configure(fg_color="#121212") 

        # --- Grid Layout (1 row, 2 columns) ---
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1) # Main chat area takes most space

        # ==========================================
        # LEFT SIDEBAR (Controls & Status)
        # ==========================================
        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0, fg_color="#1A1A1A")
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(4, weight=1) # Pushes bottom elements down

        # App Title / Logo Area
        self.logo_label = ctk.CTkLabel(self.sidebar, text="✦ NOVA", font=("Segoe UI", 24, "bold"), text_color="#FFFFFF")
        self.logo_label.grid(row=0, column=0, padx=20, pady=(30, 10), sticky="w")
        
        self.version_label = ctk.CTkLabel(self.sidebar, text="v1.0.0 Premium", font=("Segoe UI", 10), text_color="#666666")
        self.version_label.grid(row=1, column=0, padx=20, pady=(0, 30), sticky="w")

        # Sidebar Buttons (Clean, flat design)
        button_style = {
            "fg_color": "transparent", 
            "text_color": "#CCCCCC", 
            "hover_color": "#2A2A2A", 
            "anchor": "w", 
            "font": ("Segoe UI", 14)
        }
        
        self.btn_chat = ctk.CTkButton(self.sidebar, text="💬 Chat", **button_style)
        self.btn_chat = ctk.CTkButton(self.sidebar, text="💬 Chat", **button_style, command=lambda: print("Chat button clicked!"))
        self.btn_chat.grid(row=2, column=0, padx=10, pady=5, sticky="ew")

        self.btn_settings = ctk.CTkButton(self.sidebar, text="⚙️ Settings", **button_style, command=lambda: print("Settings coming soon!"))
        self.btn_settings.grid(row=3, column=0, padx=10, pady=5, sticky="ew")

        # Mic Status & Wake Word Toggle (Bottom of sidebar)
        self.status_label = ctk.CTkLabel(self.sidebar, text="🎙️ Waiting for wake word...", font=("Segoe UI", 12), text_color="#888888")
        self.status_label.grid(row=5, column=0, padx=20, pady=(10, 5), sticky="w")

        self.wake_switch = ctk.CTkSwitch(self.sidebar, text="Wake Word", progress_color="#E0E0E0", button_color="#FFFFFF", button_hover_color="#CCCCCC")
        self.wake_switch.grid(row=6, column=0, padx=20, pady=(0, 30), sticky="w")
        self.wake_switch.select() # On by default

        # ==========================================
        # RIGHT MAIN AREA (Chat & Input)
        # ==========================================
        self.main_frame = ctk.CTkFrame(self, fg_color="#121212", corner_radius=0)
        self.main_frame.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        self.main_frame.grid_rowconfigure(0, weight=1)
        self.main_frame.grid_columnconfigure(0, weight=1)

        # Chat History Text Box (Borderless, sleek)
        self.chat_box = ctk.CTkTextbox(self.main_frame, fg_color="#1A1A1A", text_color="#E0E0E0", font=("Segoe UI", 14), corner_radius=15, wrap="word")
        self.chat_box.grid(row=0, column=0, columnspan=2, sticky="nsew", pady=(0, 20))
        self.chat_box.insert("0.0", "✦ Nova initialized. How can I help you today?\n\n")
        self.chat_box.configure(state="disabled") # Read-only

        # Input Area (Bottom)
        self.entry_message = ctk.CTkEntry(self.main_frame, placeholder_text="Type a message...", height=45, corner_radius=22, fg_color="#1A1A1A", border_color="#333333", border_width=1, font=("Segoe UI", 14))
        self.entry_message.grid(row=1, column=0, sticky="ew", padx=(0, 10))
        # Bind Enter key to send
        self.entry_message.bind("<Return>", lambda event: self.send_message())

        # Send Button (Subtle accent color)
        self.btn_send = ctk.CTkButton(self.main_frame, text="Send ➔", width=80, height=45, corner_radius=22, fg_color="#333333", hover_color="#444444", font=("Segoe UI", 14, "bold"), command=self.send_message)
        self.btn_send.grid(row=1, column=1, sticky="e")

    # --- Backend Connection Functions ---
    import threading # Add this at the top of your file if it's not there!

    def send_message(self):
        user_text = self.entry_message.get()
        if not user_text.strip():
            return
            
        # 1. Show your message on screen
        self.entry_message.delete(0, 'end')
        
        # --- THE MAGIC HOOK (Finds the hidden backend automatically) ---
        if getattr(self, 'pipeline', None) is None:
            import gc
            # Searches your computer's active memory for the VoicePipeline engine
            for obj in gc.get_objects():
                if type(obj).__name__ == 'VoicePipeline':
                    self.pipeline = obj
                    break
                    
        # 2. Send the text directly to the engine
        if getattr(self, 'pipeline', None):
            import threading
            # We use a thread so the UI doesn't freeze while Nova thinks
            if hasattr(self.pipeline, 'process_text'):
                threading.Thread(target=self.pipeline.process_text, args=(user_text,), daemon=True).start()
            else:
                self.update_chat("⚠️ Error: Backend found, but it doesn't support text processing.\n\n")
        else:
            self.update_chat("⚠️ Error: Completely failed to find backend in memory.\n\n")

    def update_chat(self, text):
        self.chat_box.configure(state="normal")
        self.chat_box.insert("end", text)
        self.chat_box.see("end") # Auto-scroll
        self.chat_box.configure(state="disabled")

    # ==========================================
    # BACKEND BRIDGES (Stops all main.py crashes)
    # ==========================================
    def notify_audio_level(self, level):
        # Catches audio data so the app doesn't crash
        pass

    def notify_state(self, state):
        # Updates the little status text at the bottom left dynamically!
        # e.g., changes from "Waiting for wake word..." to "Listening..."
        if hasattr(self, 'status_label'):
            self.status_label.configure(text=f"🎙️ {state.title()}...")

    def notify_user_message(self, message):
        # Catches your transcribed voice and puts it in the chat UI
        self.update_chat(f"You: {message}\n")

    def notify_assistant_message(self, message):
        # Catches Nova's response and puts it in the chat UI
        self.update_chat(f"Nova: {message}\n\n")

    def notify_error(self, error_msg):
        # Catches any backend errors so they show in the UI instead of crashing
        self.update_chat(f"⚠️ Error: {error_msg}\n\n")

    def on_close(self):
        # Ensures safe shutdown if main.py tries to close the window
        self.destroy()

if __name__ == "__main__":
    app = NovaApp()
    app.mainloop()