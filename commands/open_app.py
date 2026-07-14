import os

def handle(entities):
    # Notice it matches the entity key from your terminal logs: 'app_name'
    app_name = entities.get('app_name', '').lower()
    
    if 'edge' in app_name:
        os.system("start msedge")
        return "Opening Microsoft Edge."
        
    elif 'notepad' in app_name:
        os.system("start notepad")
        return "Opening Notepad."
        br
    elif 'brave' in app_name:
        # We give Windows the exact location of the Brave executable
        brave_path = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
        
        # os.startfile is a great, reliable way to open exact paths on Windows
        try:
            os.startfile(brave_path)
            return "Trying to open brave."
        except FileNotFoundError:
            return "Bhai, I couldn't find Brave at the default installation path."
            
    else:
        return f"Sorry, I don't know how to open {app_name} yet."